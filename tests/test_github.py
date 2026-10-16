from dataclasses import replace

import httpx
import pytest

from issue_agent.github import GitHubAdapter
from issue_agent.security import DomainError
from issue_agent.server import ToolService

REPO = "student-lab/course-project"


@pytest.mark.parametrize(
    "headers,page,next_page,truncated",
    [
        ({"Link": '<https://api.github.com/ignored?page=2>; rel="next"'}, 1, 2, True),
        ({}, 1, 2, True),
        ({"Link": '<https://api.github.com/ignored?page=1>; rel="prev"'}, 2, None, False),
        ({"Link": '<https://api.github.com/ignored?page=4>; rel="next"'}, 3, None, True),
    ],
)
async def test_pagination_uses_upstream_page_before_filtering_prs(
    settings, store, headers, page, next_page, truncated
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers=headers,
            json=[{"number": 1, "pull_request": {}}, {"number": 2, "title": "Issue"}],
        )

    adapter = GitHubAdapter(settings, store, transport=httpx.MockTransport(handler))
    result = await adapter.execute(
        "list_open_issues", {"repo": REPO, "page": page, "per_page": 2}, "pr-page"
    )
    assert [item["number"] for item in result["data"]] == [2]
    assert result["next_page"] == next_page
    assert result["truncated"] is truncated
    assert len(requests) == 1
    assert requests[0].url.path == f"/repos/{REPO}/issues"


@pytest.mark.parametrize(
    "status,code,attempts",
    [
        (401, "GITHUB_401", 1),
        (403, "GITHUB_403", 1),
        (404, "GITHUB_404", 1),
        (409, "GITHUB_409", 1),
        (422, "GITHUB_422", 1),
        (429, "GITHUB_RATE_LIMIT", 1),
        (500, "GITHUB_5XX", 3),
        (503, "GITHUB_5XX", 3),
        (302, "GITHUB_UNEXPECTED_STATUS", 1),
    ],
)
async def test_status_errors(settings, store, status, code, attempts):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"message": "secret must not escape"})

    adapter = GitHubAdapter(settings, store, transport=httpx.MockTransport(handler))
    with pytest.raises(DomainError, match=code):
        await adapter.execute("get_repository", {"repo": REPO}, "status")
    assert len(requests) == attempts
    assert all(request.url.host == "api.github.com" for request in requests)
    assert "secret must not escape" not in str(store.events("system"))


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
@pytest.mark.parametrize("write", [True, False])
async def test_transport_errors(settings, store, error, write):
    requests = []

    def handler(request):
        requests.append(request)
        raise error("Token xyz should not be logged")

    adapter = GitHubAdapter(settings, store, transport=httpx.MockTransport(handler))
    with pytest.raises(DomainError) as exc:
        await adapter.request("POST" if write else "GET", "/repos/a/b", {}, None, "transport")
    assert exc.value.uncertain == write
    assert len(requests) == (1 if write else 3)


async def test_retry_recovers_and_budget(settings, store):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(503 if count == 1 else 200, json={"ok": True})

    adapter = GitHubAdapter(settings, store, transport=httpx.MockTransport(handler))
    assert (await adapter.execute("get_repository", {"repo": REPO}, "retry"))["requests_used"] == 2
    limited = GitHubAdapter(
        replace(settings, request_budget=1), store, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(DomainError, match="REQUEST_BUDGET_EXHAUSTED"):
        await limited.execute("get_repository", {"repo": REPO}, "retry")


@pytest.mark.parametrize(
    "content,code",
    [
        (b"not-json", "GITHUB_INVALID_JSON"),
        (b"true", "GITHUB_INVALID_RESPONSE"),
        (b"x" * 100, "GITHUB_RESPONSE_TOO_LARGE"),
    ],
)
async def test_response_bounds(settings, store, content, code):
    adapter = GitHubAdapter(
        replace(settings, response_limit=60),
        store,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content)),
    )
    with pytest.raises(DomainError, match=code):
        await adapter.execute("get_repository", {"repo": REPO}, "bounds")


async def test_rate_metadata_and_token_redaction(settings, store):
    secret = "custom-secret-pat-value"
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"body": secret},
            headers={"x-ratelimit-remaining": "41", "x-ratelimit-reset": secret},
        )

    adapter = GitHubAdapter(
        replace(settings, github_mode="real"),
        store,
        token=secret,
        transport=httpx.MockTransport(handler),
    )
    result = await adapter.execute("get_repository", {"repo": REPO}, "rate")
    assert requests[0].headers["authorization"] == f"Bearer {secret}"
    assert result["data"]["body"] == "[REDACTED]"
    assert result["rate_limit"] == {"x-ratelimit-remaining": "41"}
    assert secret not in str(store.events("system"))


@pytest.mark.parametrize("headers", [{"x-ratelimit-remaining": "0"}, {"retry-after": "60"}])
async def test_secondary_rate_limit(settings, store, headers):
    adapter = GitHubAdapter(
        settings,
        store,
        transport=httpx.MockTransport(lambda _: httpx.Response(403, json={}, headers=headers)),
    )
    with pytest.raises(DomainError, match="GITHUB_RATE_LIMIT"):
        await adapter.execute("get_repository", {"repo": REPO}, "secondary")


async def test_mock_all_endpoints(settings, store):
    service = ToolService(settings)
    base = {"repo": REPO}
    reads = [
        ("get_repository", base),
        ("get_issue", base | {"issue_number": 1}),
        ("list_open_issues", base | {"per_page": 2}),
        ("list_labels", base),
        ("get_issue_comments", base | {"issue_number": 1}),
        ("search_issues", base | {"query": "login"}),
    ]
    for tool, args in reads:
        result = await service.call(tool, args, "mock")
        assert result["ok"], result
    page = await service.call("list_open_issues", base | {"per_page": 2}, "mock")
    assert page["next_page"] == 2
    for tool, args in [
        ("post_comment", base | {"issue_number": 1, "body": "hello"}),
        ("add_labels", base | {"issue_number": 1, "labels": ["bug"]}),
        ("create_issue", base | {"title": "New issue", "body": "Details"}),
    ]:
        assert not (await service.call(tool, args, "mock"))["ok"]
        action = store.pending("s", tool, args, "Test")
        proof = store.decide("s", action["id"], True)
        assert (await service.call(tool, args, "mock", proof))["ok"]
        assert store.get_action("s", action["id"])["status"] == "SUCCEEDED"
    assert (
        len((await service.call("get_issue_comments", base | {"issue_number": 1}, "mock"))["data"])
        == 1
    )
    assert (await service.call("shell", {}, "mock"))["error"] == "BLOCK_UNKNOWN_TOOL"


@pytest.mark.parametrize(
    "issue_number,code",
    [
        (401, "GITHUB_401"),
        (403, "GITHUB_403"),
        (404, "GITHUB_404"),
        (409, "GITHUB_409"),
        (422, "GITHUB_422"),
        (429, "GITHUB_RATE_LIMIT"),
        (500, "GITHUB_5XX"),
        (503, "GITHUB_5XX"),
        (408, "GITHUB_TIMEOUT"),
        (999, "GITHUB_404"),
    ],
)
async def test_mock_faults(settings, issue_number, code):
    result = await ToolService(settings).call(
        "get_issue", {"repo": REPO, "issue_number": issue_number}, "fault"
    )
    assert result["error"] == code


@pytest.mark.parametrize(
    "failure,status", [(httpx.ReadTimeout, "UNKNOWN"), (RuntimeError, "UNKNOWN")]
)
async def test_write_unknown_not_replayed(settings, store, failure, status):
    writes = []

    def handler(request):
        writes.append(request)
        raise failure("Synthetic lost response")

    service = ToolService(
        settings, GitHubAdapter(settings, store, transport=httpx.MockTransport(handler))
    )
    args = {"repo": REPO, "issue_number": 1, "body": "Possible write"}
    action = store.pending("s", "post_comment", args, "Comment")
    proof = store.decide("s", action["id"], True)
    assert not (await service.call("post_comment", args, "unknown", proof))["ok"]
    assert store.get_action("s", action["id"])["status"] == status
    await service.call("post_comment", args, "unknown", proof)
    assert len(writes) == 1


async def test_write_422_is_terminal(settings, store):
    args = {"repo": REPO, "issue_number": 1, "labels": ["not-existing"]}
    action = store.pending("s", "add_labels", args, "Labels")
    proof = store.decide("s", action["id"], True)
    result = await ToolService(settings).call("add_labels", args, "invalid-label", proof)
    assert result["error"] == "GITHUB_422"
    assert store.get_action("s", action["id"])["status"] == "FAILED"


async def test_pull_request_excluded(settings, store):
    adapter = GitHubAdapter(
        settings,
        store,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"pull_request": {}, "number": 1})
        ),
    )
    with pytest.raises(DomainError, match="BLOCK_PULL_REQUEST"):
        await adapter.execute("get_issue", {"repo": REPO, "issue_number": 1}, "pr")


def test_real_token_required(settings, store, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(DomainError, match="GITHUB_TOKEN_MISSING"):
        GitHubAdapter.for_server(replace(settings, github_mode="real"), store)
