"""Validate only this Compose project, using mock GitHub and real MCP HTTP."""

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

import httpx


def command(*args: str) -> str:
    completed = subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8")
    return completed.stdout.strip()


def stats() -> dict[str, int]:
    code = (
        "import sqlite3,json; d=sqlite3.connect('/data/agent.sqlite3'); print(json.dumps({"
        "'comments':d.execute('SELECT COUNT(*) FROM mock_comments').fetchone()[0],"
        "'post_requests':d.execute(\"SELECT COUNT(*) FROM mock_requests "
        "WHERE method='POST'\").fetchone()[0]}))"
    )
    return json.loads(command("docker", "compose", "exec", "-T", "mcp", "python", "-c", code))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8021")
    args = parser.parse_args()
    output = Path("artifacts/docker")
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"github_mode": "mock", "real_github": False, "real_writes": False, "checks": {}}
    evidence["checks"]["build_and_start"] = command(
        "docker", "compose", "up", "-d", "--build", "--wait"
    )
    for service in ("mcp", "web"):
        uid = command("docker", "compose", "exec", "-T", service, "id", "-u")
        assert uid == "10001"
        evidence["checks"][f"{service}_uid"] = uid
        container = command("docker", "compose", "ps", "-q", service)
        state = json.loads(command("docker", "inspect", "--format", "{{json .State}}", container))
        assert state["Health"]["Status"] == "healthy"
        evidence["checks"][f"{service}_health"] = state["Health"]["Status"]
    probe = """import asyncio,json
from mcp import Client
async def main():
    async with Client('http://mcp:8022/mcp') as c:
        catalog=await c.list_tools()
        arguments={'repo':'student-lab/course-project','issue_number':1,'body':'Must be blocked'}
        r=await c.call_tool('post_comment',{'args':arguments})
        print(json.dumps({'protocol':c.protocol_version,'tools':len(catalog.tools),
                          'result':r.structured_content}))
asyncio.run(main())
"""
    before = stats()
    unapproved = json.loads(
        command("docker", "compose", "exec", "-T", "web", "python", "-c", probe)
    )
    assert unapproved["result"]["error"] == "REQUIRE_CONFIRM"
    assert stats() == before
    evidence["checks"]["raw_mcp_unapproved"] = unapproved
    with httpx.Client(base_url=args.url, timeout=60, trust_env=False) as client:
        assert client.get("/").status_code == 200
        evidence["checks"]["ready"] = client.get("/ready").json()
        session = client.get("/api/session").json()
        assert session["github_mode"] == "mock"
        headers = {"x-csrf-token": session["csrf"]}
        task = client.post(
            "/api/tasks",
            headers=headers,
            json={
                "repo": "student-lab/course-project",
                "issue": 1,
                "task": "Triage missing information",
                "mode": "offline",
                "allow_writes": False,
            },
        ).json()
        assert task["status"] == "completed" and len(task["trace"]) == 6, task
        evidence["checks"]["read_task"] = {
            "status": task["status"],
            "tool_calls": len(task["trace"]),
            "protocol": task["protocol_version"],
        }
        proposal = {
            "tool": "post_comment",
            "arguments": {
                "repo": "student-lab/course-project",
                "issue_number": 1,
                "body": "Docker verification " + uuid.uuid4().hex,
            },
            "impact": "One mock comment",
        }
        action = client.post("/api/proposals", headers=headers, json=proposal).json()
        assert stats() == before
        url = f"/api/actions/{action['id']}/approve"
        approved = client.post(url, headers=headers, json={"fingerprint": action["fingerprint"]})
        assert approved.status_code == 200, approved.text
        assert approved.json()["action"]["status"] == "SUCCEEDED", approved.text
        after = stats()
        assert after["comments"] == before["comments"] + 1
        assert after["post_requests"] == before["post_requests"] + 1
        duplicate = client.post(url, headers=headers, json={"fingerprint": action["fingerprint"]})
        assert duplicate.status_code == 409, duplicate.text
        assert stats() == after
        evidence["checks"]["approved_once"] = {
            "before": before,
            "after": after,
            "repeat_status": 409,
        }
        proposal["arguments"]["body"] += " pending after restart"
        pending = client.post("/api/proposals", headers=headers, json=proposal).json()
        command("docker", "compose", "restart")
        for _attempt in range(40):
            try:
                if client.get("/ready").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(1)
        else:
            raise AssertionError("Services did not recover after restart")
        states = {a["id"]: a["status"] for a in client.get("/api/actions").json()}
        assert states[action["id"]] == "SUCCEEDED" and states[pending["id"]] == "PENDING"
        assert stats() == after
        rejected = client.post(
            f"/api/actions/{pending['id']}/reject",
            headers=headers,
            json={"fingerprint": pending["fingerprint"]},
        )
        assert rejected.json()["action"]["status"] == "REJECTED"
        assert stats() == after
        evidence["checks"]["restart"] = {
            "completed": "SUCCEEDED",
            "pending": "PENDING",
            "rejected_after_restart": True,
            "extra_writes": 0,
        }
    evidence["passed"] = True
    (output / "verification.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
