import json
import uuid
from dataclasses import replace

import httpx
import pytest
from mcp import Client

from issue_agent.agent import model_loop, persist_proposals, run_task
from issue_agent.client import MCPGateway, connect
from issue_agent.models import ActionDraft, TaskRequest, TaskResult, TriageProposal
from issue_agent.provider import CompatibleProvider
from issue_agent.security import READ_TOOLS, DomainError, Policy
from issue_agent.server import build_server

REPO = "student-lab/course-project"


def request(**kwargs):
    return TaskRequest(repo=REPO, issue=1, task="Triage issue", **kwargs)


def calls(*names, args=None):
    return {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(
                                    args
                                    or (
                                        {"repo": REPO, "issue_number": 1}
                                        if name == "get_issue"
                                        else {"repo": REPO}
                                    )
                                ),
                            },
                        }
                        for i, name in enumerate(names)
                    ]
                }
            }
        ]
    }


class ScriptedProvider:
    """Test double, not a model and never reported as provider accuracy."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.seen = []

    async def complete(self, messages, tools, *, final=False):
        self.seen.append((list(messages), tools, final))
        return next(self.responses)


async def test_stdio_and_legacy(settings):
    for legacy in (False, True):
        async with connect(settings, uuid.uuid4().hex, legacy=legacy) as gateway:
            assert len(gateway.tools) == 9
            assert gateway.client.protocol_version == ("2025-11-25" if legacy else "2026-07-28")
            result = await gateway.call("get_issue", {"repo": REPO, "issue_number": 1})
            assert result["data"]["number"] == 1
            with pytest.raises(DomainError, match="REQUIRE_CONFIRM"):
                await gateway.call(
                    "post_comment", {"repo": REPO, "issue_number": 1, "body": "No approval"}
                )
            schemas = gateway.model_tools()
            assert {t["function"]["name"] for t in schemas} == set(READ_TOOLS)
            assert all(
                "authorization" not in t["function"]["parameters"]["properties"] for t in schemas
            )


@pytest.mark.parametrize("number", [1, 2, 3, 4, 5])
async def test_offline_flow(settings, store, number):
    result = await run_task(
        settings, store, "s", TaskRequest(repo=REPO, issue=number, task="Triage")
    )
    assert result.status == "completed", result.error
    assert result.mode == "offline" and result.rounds == 3
    assert len(result.trace) == 6 and result.usage is None
    assert not result.pending_actions
    assert result.proposal
    if number == 2:
        assert result.proposal.missing_information == []
    with store.connection() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM mock_requests WHERE method='POST'").fetchone()[0] == 0
        )


async def test_proposals_and_missing_provider(settings, store, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    result = await run_task(
        settings,
        store,
        "s",
        TaskRequest(
            repo=REPO, issue=1, task="create follow-up", allow_writes=True, mode="provider"
        ),
    )
    assert result.mode == "offline" and result.error == "PROVIDER_NOT_CONFIGURED"
    assert len(result.pending_actions) == 3 and result.status == "awaiting_approval"


async def test_block_and_failure(settings, store):
    result = await run_task(
        settings, store, "s", TaskRequest(repo="evil/repo", issue=1, task="Triage")
    )
    assert result.error == "BLOCK_REPOSITORY" and not result.trace
    result = await run_task(settings, store, "s", TaskRequest(repo=REPO, issue=429, task="Triage"))
    assert result.error == "GITHUB_RATE_LIMIT" and len(result.trace) == 2
    with pytest.raises(DomainError, match="REAL_MODE_REQUIRES"):
        async with connect(replace(settings, github_mode="real"), "r"):
            pass


async def test_scripted_tool_loop(settings):
    proposal = TriageProposal(summary="Login error", issue_type="bug")
    provider = ScriptedProvider(
        [
            calls("get_repository", "get_issue"),
            {
                "choices": [{"message": {"content": proposal.model_dump_json()}}],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                    "cost_usd": 0.002,
                },
            },
        ]
    )
    async with Client(build_server(settings)) as client:
        gateway = MCPGateway(client, Policy((REPO,)), "scripted")
        await gateway.discover()
        result = TaskResult(run_id="x", mode="scripted", github_mode="mock", status="running")
        actual = await model_loop(gateway, request(), 1, provider, result)
        assert actual.summary == "Login error" and result.rounds == 1
        assert result.usage["total_tokens"] == 15 and result.cost_usd == 0.002
        assert "untrusted_data" in provider.seen[1][0][-1]["content"]


async def test_invalid_action_arguments_get_one_repair_turn(settings):
    def answer(arguments):
        proposal = TriageProposal(
            summary="Follow-up needed",
            issue_type="bug",
            actions=[
                {"tool": "create_issue", "arguments": arguments, "impact": "Create one issue."}
            ],
        )
        return {"choices": [{"message": {"content": proposal.model_dump_json()}}]}

    good = {"repo": REPO, "title": "Follow-up", "body": "Details"}
    provider = ScriptedProvider(
        [calls("get_repository", "get_issue"), answer(good | {"labels": ["bug"]}), answer(good)]
    )
    async with Client(build_server(settings)) as client:
        gateway = MCPGateway(client, Policy((REPO,)), "repair")
        await gateway.discover()
        result = TaskResult(run_id="x", mode="scripted", github_mode="mock", status="running")
        actual = await model_loop(gateway, request(), 1, provider, result)
        assert actual.actions[0].arguments == good and result.repair_rounds == 1
        feedback = provider.seen[2][0][-1]["content"]
        assert "actions.0.arguments.labels" in feedback
        # The repair turn executes nothing: only the two read calls reached MCP.
        assert [t.tool for t in gateway.trace] == ["get_repository", "get_issue"]


@pytest.mark.parametrize(
    "responses,code",
    [
        ([calls("delete_issue")], "BLOCK_MODEL_TOOL"),
        ([calls("post_comment")], "BLOCK_MODEL_TOOL"),
        ([calls("read_env")], "BLOCK_MODEL_TOOL"),
        ([calls("get_issue", args={"repo": REPO, "issue_number": 2})], "BLOCK_MODEL_SCOPE"),
        ([calls("get_issue", args={"repo": REPO, "issue_number": "1"})], "BLOCK_INVALID_ARGUMENTS"),
        (
            [calls("get_repository", "get_repository", "get_repository", "get_repository")],
            "AGENT_CALL_BUDGET",
        ),
        ([calls("get_repository")] * 5, "AGENT_ROUND_BUDGET"),
        ([{"choices": [{"message": {"content": "{}"}}]}], "MISSING_REQUIRED_OBSERVATIONS"),
        ([{}], "MODEL_INVALID_OUTPUT"),
        (
            [
                calls("get_repository", "get_issue"),
                {"choices": [{"message": {"content": "not json"}}]},
                {"choices": [{"message": {"content": "still not json"}}]},
            ],
            "MODEL_INVALID_OUTPUT",
        ),
    ],
)
async def test_scripted_attacks(settings, responses, code):
    async with Client(build_server(settings)) as client:
        gateway = MCPGateway(client, Policy((REPO,)), uuid.uuid4().hex)
        await gateway.discover()
        result = TaskResult(run_id="x", mode="scripted", github_mode="mock", status="running")
        with pytest.raises(DomainError, match=code):
            await model_loop(gateway, request(), 1, ScriptedProvider(responses), result)
        assert result.rounds <= 4
        assert all(t.tool in READ_TOOLS for t in gateway.trace)


def test_proposal_scope(store):
    action = ActionDraft(
        tool="post_comment", arguments={"repo": REPO, "issue_number": 2, "body": "a"}, impact="a"
    )
    proposal = TriageProposal(summary="a", issue_type="bug", actions=[action])
    with pytest.raises(DomainError, match="BLOCK_WRITE_PROPOSAL"):
        persist_proposals(store, "s", request(), 1, proposal, Policy((REPO,)), 300)
    with pytest.raises(DomainError, match="BLOCK_ACTION_SCOPE"):
        persist_proposals(store, "s", request(allow_writes=True), 1, proposal, Policy((REPO,)), 300)


async def test_provider_http_adapter(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "never-output-this-key")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.test/v1")
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(200, json={"choices": []})

    provider = CompatibleProvider(transport=httpx.MockTransport(handler))
    assert await provider.complete([], [{"type": "function"}]) == {"choices": []}
    await provider.complete([], [], final=True)
    assert "never-output-this-key" not in requests[0].content.decode()
    assert "tools" in json.loads(requests[0].content)
    assert "tools" not in json.loads(requests[1].content)
    bad = CompatibleProvider(transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    with pytest.raises(DomainError, match="PROVIDER_UNAVAILABLE"):
        await bad.complete([], [])
    monkeypatch.setenv("MODEL_BASE_URL", "http://example.test/v1")
    with pytest.raises(DomainError, match="INVALID_PROVIDER_URL"):
        CompatibleProvider()
