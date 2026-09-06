import argparse
import asyncio
import csv
import json
import math
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from issue_agent.agent import model_loop, run_task
from issue_agent.client import MCPGateway, connect
from issue_agent.config import Settings
from issue_agent.models import TaskRequest, TaskResult, TriageProposal
from issue_agent.security import TOOL_MODELS, DomainError, canonical
from issue_agent.storage import Store

REPO = "student-lab/course-project"


class ScriptedRegressionProvider:
    """Fixed control-flow fixture, deliberately not a real model."""

    def __init__(self, scenario: str) -> None:
        self.scenario, self.turn = scenario, 0

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, final: bool = False
    ) -> dict[str, Any]:
        self.turn += 1
        if self.scenario == "missing_evidence" or (self.scenario == "valid" and self.turn > 1):
            message: dict[str, Any] = {
                "content": TriageProposal(
                    summary="Synthetic triage", issue_type="bug"
                ).model_dump_json()
            }
        else:
            name = {
                "unknown": "imaginary_tool",
                "write": "post_comment",
                "read_secret": "read_env",
                "budget": "get_repository",
                "bad_type": "get_issue",
                "scope": "get_issue",
                "valid": "get_issue",
            }[self.scenario]
            args: dict[str, Any] = {"repo": REPO}
            if name == "get_issue":
                args["issue_number"] = (
                    "1" if self.scenario == "bad_type" else 2 if self.scenario == "scope" else 1
                )
            calls = [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": name, "arguments": canonical(args)},
                }
            ]
            if self.scenario == "valid":
                calls.append(
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "get_repository",
                            "arguments": canonical({"repo": REPO}),
                        },
                    }
                )
            message = {"tool_calls": calls}
        return {"choices": [{"message": message}]}


def write_count(store: Store) -> int:
    with store.connection() as db:
        return int(
            db.execute("SELECT COUNT(*) FROM mock_requests WHERE method='POST'").fetchone()[0]
        )


async def approval_case(gateway: MCPGateway, store: Store, case: dict[str, Any]) -> str:
    scenario, session = case["scenario"], uuid.uuid4().hex
    args = {"repo": REPO, "issue_number": 1, "body": "Synthetic regression " + case["id"]}
    action = store.pending(
        session, "post_comment", args, "Post a mock comment", -1 if scenario == "expired" else 300
    )
    if scenario == "reject":
        store.decide(session, action["id"], False)
        return str(store.get_action(session, action["id"])["status"])
    proof = store.decide(session, action["id"], True)
    assert proof is not None
    if scenario == "changed":
        args["body"] += " changed"
    if scenario == "wrong_session":
        proof = proof.model_copy(update={"session_id": "other"})
    if scenario == "restart":
        store = Store(store.path)
        assert store.get_action(session, action["id"])["status"] == "APPROVED"
    await gateway.call("post_comment", args, proof)
    if scenario == "repeat":
        await gateway.call("post_comment", args, proof)
    if scenario == "new_action_duplicate":
        second = store.pending("other", "post_comment", args, "Same fingerprint")
        await gateway.call("post_comment", args, store.decide("other", second["id"], True))
    return str(store.get_action(session, action["id"])["status"])


async def evaluate_case(
    settings: Settings, store: Store, gateway: MCPGateway, case: dict[str, Any], mode: str
) -> dict[str, Any]:
    start, before = time.perf_counter(), write_count(store)
    gateway.run_id = uuid.uuid4().hex
    gateway.trace = []
    row: dict[str, Any] = {
        "id": case["id"],
        "kind": case["kind"],
        "expected": case["expected"],
        "passed": False,
        "discovery": False,
        "permission_correct": None,
        "schema_valid": None,
        "unauthorized_writes": 0,
        "rounds": 0,
        "usage": None,
        "cost_usd": None,
        "trace": [],
    }
    try:
        await gateway.discover()
        row["discovery"] = True
        kind = case["kind"]
        if kind == "task":
            request = TaskRequest(
                repo=REPO,
                issue=case["issue"],
                task=case["task"],
                allow_writes=case.get("write", False),
                mode="provider" if mode == "provider" else "offline",
            )
            result = await run_task(settings, store, uuid.uuid4().hex, request)
            row.update(
                observed=result.status,
                rounds=result.rounds,
                usage=result.usage,
                cost_usd=result.cost_usd,
                trace=[t.model_dump(mode="json") for t in result.trace],
                result=result.model_dump(mode="json"),
            )
            row["passed"] = result.status == case["expected"] and (
                not case.get("error") or result.error == case["error"]
            )
            if mode == "offline" and result.proposal:
                for key, actual in [
                    ("missing", len(result.proposal.missing_information)),
                    ("actions", len(result.pending_actions)),
                ]:
                    if key in case:
                        row["passed"] &= actual == case[key]
                if "label" in case:
                    row["passed"] &= case["label"] in result.proposal.suggested_labels
            if mode == "provider":
                row["real_provider"] = result.provider_responses > 0
                if result.mode != "provider":
                    row["passed"] = False
                observed_tools = {t.tool for t in result.trace if t.status == "ok"}
                row["tool_selection_correct"] = (
                    (
                        {"get_repository", "get_issue"}.issubset(observed_tools)
                        and result.error != "BLOCK_MODEL_TOOL"
                    )
                    if row["real_provider"]
                    else None
                )
        elif kind in {"tool", "fault"}:
            tool = case.get("tool", "get_issue")
            args = {"repo": REPO} | case.get("args", {"issue_number": case.get("issue", 1)})
            if "permission" in case:
                row["permission_correct"] = (
                    gateway.policy.decide(tool, args).value == case["permission"]
                )
            if tool in TOOL_MODELS:
                row["schema_valid"] = Draft202012Validator(
                    TOOL_MODELS[tool].model_json_schema()
                ).is_valid(args)
            await gateway.call(tool, args)
            row["observed"] = "ok"
            row["passed"] = case["expected"] == "ok"
        elif kind == "approval":
            row["observed"] = await approval_case(gateway, store, case)
            row["passed"] = row["observed"] == case["expected"]
        else:
            state = TaskResult(
                run_id=gateway.run_id, mode="scripted", github_mode="mock", status="running"
            )
            try:
                await model_loop(
                    gateway,
                    TaskRequest(repo=REPO, issue=1, task="Triage"),
                    1,
                    ScriptedRegressionProvider(case["scenario"]),
                    state,
                )
                row["observed"], row["passed"] = "completed", case["expected"] == "completed"
            finally:
                row["rounds"] = state.rounds
    except DomainError as exc:
        row["observed"], row["passed"] = exc.code, exc.code == case["expected"]
    except Exception as exc:
        row["observed"] = type(exc).__name__
    after = write_count(store)
    authorized = (
        1
        if case["kind"] == "approval"
        and case["scenario"] in {"approve", "repeat", "restart", "new_action_duplicate"}
        else 0
    )
    row["unauthorized_writes"] = max(0, after - before - authorized)
    row["passed"] &= row["unauthorized_writes"] == 0 and row["permission_correct"] is not False
    row["trace"] = row["trace"] or [t.model_dump(mode="json") for t in gateway.trace]
    row["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return row


def ratio(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize(rows: list[dict[str, Any]], cases: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    latencies = sorted(row["latency_ms"] for row in rows)
    calls = [trace for row in rows for trace in row["trace"]]
    attacks = {c["id"] for c in cases if c.get("attack")}
    duplicates = {c["id"] for c in cases if c.get("duplicate")}
    return {
        "mode": mode,
        "source": "AI-assisted synthetic regression set",
        "case_count": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "mcp_discovery_success_rate": ratio([r["discovery"] for r in rows]),
        "tool_call_success_rate": ratio([t["status"] == "ok" for t in calls]),
        "tool_selection_accuracy": ratio(
            [
                r["tool_selection_correct"]
                for r in rows
                if r.get("tool_selection_correct") is not None
            ]
        )
        if mode == "provider"
        else None,
        "parameter_schema_pass_rate": ratio(
            [r["schema_valid"] for r in rows if r["schema_valid"] is not None]
        ),
        "permission_accuracy": ratio(
            [r["permission_correct"] for r in rows if r["permission_correct"] is not None]
        ),
        "forbidden_operation_block_rate": ratio([r["passed"] for r in rows if r["id"] in attacks]),
        "unauthorized_writes": sum(r["unauthorized_writes"] for r in rows),
        "duplicate_write_suppression_rate": ratio(
            [r["passed"] for r in rows if r["id"] in duplicates]
        ),
        "e2e_expected_outcome_rate": ratio([r["passed"] for r in rows]),
        "p50_ms": latencies[math.ceil(len(latencies) * 0.50) - 1],
        "p95_ms": latencies[math.ceil(len(latencies) * 0.95) - 1],
        "max_tool_rounds": max(r["rounds"] for r in rows),
        "tool_call_count": len(calls),
        "usage": [r["usage"] for r in rows if r["usage"]] or None,
        "cost_usd": sum(r["cost_usd"] for r in rows if r["cost_usd"] is not None)
        if any(r["cost_usd"] is not None for r in rows)
        else None,
    }


async def evaluate(dataset: Path, output: Path, mode: str = "offline") -> dict[str, Any]:
    raw = json.loads(dataset.read_text(encoding="utf-8"))
    cases = raw["cases"]
    if mode == "provider":
        cases = [c for c in cases if c["kind"] == "task" and not c.get("attack")]
    rows = []
    with tempfile.TemporaryDirectory(prefix="issue-eval-") as directory:
        settings = Settings(data_dir=Path(directory))
        store = Store(settings.db_path)
        async with connect(settings, uuid.uuid4().hex) as gateway:
            for case in cases:
                row = await evaluate_case(settings, store, gateway, case, mode)
                rows.append(row)
                print(f"{row['id']}: {'PASS' if row['passed'] else 'FAIL'} ({row.get('observed')})")
    summary = summarize(rows, cases, mode)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(
        json.dumps({"summary": summary, "cases": rows}, indent=2), encoding="utf-8"
    )
    (output / "cases.jsonl").write_text(
        "\n".join(canonical(row) for row in rows) + "\n", encoding="utf-8"
    )
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "id",
                "kind",
                "expected",
                "observed",
                "passed",
                "latency_ms",
                "rounds",
                "unauthorized_writes",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    report = [
        f"# {mode.title()} Evaluation",
        "",
        "Source: AI-assisted synthetic regression set.",
        "No real GitHub requests or writes. Scripted provider cases are control-flow fixtures, "
        "not model results.",
        "Expected security rejections count as correct outcomes, not successful tool executions.",
        "Schema pass rate includes deliberately invalid cases. "
        "Latency is local and not a production SLA.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    report += [
        f"| {key} | {value if value is not None else 'not measured'} |"
        for key, value in summary.items()
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evals/cases.json"))
    parser.add_argument("--mode", choices=["offline", "provider"], default="offline")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = asyncio.run(
        evaluate(args.dataset, args.output or Path("artifacts") / args.mode, args.mode)
    )
    print(json.dumps(summary, indent=2))
    if summary["passed"] != summary["case_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
