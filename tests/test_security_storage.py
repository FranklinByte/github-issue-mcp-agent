import concurrent.futures
import json
import time

import pytest

from issue_agent.config import Settings
from issue_agent.models import Permission
from issue_agent.security import DomainError, Policy, canonical, digest, parse_issue, redact
from issue_agent.storage import Store

REPO = "student-lab/course-project"
ARGS = {"repo": REPO, "issue_number": 1, "body": "Please add steps."}


@pytest.mark.parametrize(
    "tool,args,expected",
    [
        ("get_repository", {"repo": REPO}, Permission.ALLOW),
        ("post_comment", ARGS, Permission.REQUIRE_CONFIRM),
        ("delete_issue", {"repo": REPO}, Permission.BLOCK),
        ("close_issue", {"repo": REPO}, Permission.BLOCK),
        ("shell", {"command": "whoami"}, Permission.BLOCK),
        ("get_issue", {"repo": "attacker/repo", "issue_number": 1}, Permission.BLOCK),
        ("get_issue", {"repo": REPO, "issue_number": "1"}, Permission.BLOCK),
        ("get_issue", {"repo": REPO, "issue_number": True}, Permission.BLOCK),
        ("get_issue", {"repo": REPO, "issue_number": 0}, Permission.BLOCK),
        ("get_issue", {"repo": REPO}, Permission.BLOCK),
        ("get_repository", {"repo": REPO, "url": "http://localhost"}, Permission.BLOCK),
        ("get_repository", {"repo": "student-lab/.."}, Permission.BLOCK),
        ("search_issues", {"repo": REPO, "query": "repo:attacker/repo"}, Permission.BLOCK),
        ("list_labels", {"repo": REPO, "page": 4}, Permission.BLOCK),
        ("add_labels", {"repo": REPO, "issue_number": 1, "labels": []}, Permission.BLOCK),
    ],
)
def test_policy(tool, args, expected):
    assert Policy((REPO,)).decide(tool, args) == expected


@pytest.mark.parametrize("value", [1, "1", f"https://github.com/{REPO}/issues/1"])
def test_issue_input(value):
    assert parse_issue(REPO, value) == 1


@pytest.mark.parametrize(
    "value",
    [
        False,
        0,
        -1,
        "foo",
        "https://evil.test/a/b/issues/1",
        f"https://github.com/{REPO}/issues/1?token=a",
        f"https://github.com/{REPO}/pull/1",
        "https://github.com/attacker/repo/issues/1",
        "http://127.0.0.1",
        "1/../2",
    ],
)
def test_issue_input_block(value):
    with pytest.raises(DomainError):
        parse_issue(REPO, value)


def test_redaction():
    raw = {
        "token": "a",
        "body": "Bearer secret ghp_1234 github_pat_123 sk-abcdefghi REALSECRET",
        "nested": [{"api_key": "b"}],
    }
    safe = json.dumps(redact(raw, ("REALSECRET",)))
    assert "REALSECRET" not in safe and "ghp_" not in safe and "Bearer" not in safe
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})


def test_sessions(store):
    cookie, csrf = store.session(None)
    assert store.session(cookie) == (cookie, csrf)
    assert store.require_session(cookie, csrf) == digest(cookie)
    with pytest.raises(DomainError):
        store.require_session(cookie, "wrong")
    with pytest.raises(DomainError):
        store.require_session("wrong")


def prepare(store, *, session="s", args=None, ttl=300):
    action = store.pending(session, "post_comment", args or ARGS, "Comment", ttl)
    proof = store.decide(session, action["id"], True)
    assert proof is not None
    return action, proof


def test_approval_once_restart(store):
    action, proof = prepare(store)
    restarted = Store(store.path)
    assert restarted.claim("post_comment", ARGS, proof) == action["id"]
    restarted.finish(action["id"], "SUCCEEDED", {"ok": True})
    with pytest.raises(DomainError, match="APPROVAL_ALREADY_USED"):
        store.claim("post_comment", ARGS, proof)
    assert store.get_action("s", action["id"])["status"] == "SUCCEEDED"
    assert "token" not in json.dumps(store.events("s"))


def test_binding_and_invalidated(store):
    action, proof = prepare(store)
    with pytest.raises(DomainError):
        store.claim("post_comment", ARGS, proof.model_copy(update={"session_id": "other"}))
    with pytest.raises(DomainError):
        store.claim("post_comment", ARGS, proof.model_copy(update={"token": "wrong"}))
    with pytest.raises(DomainError, match="BLOCK_APPROVAL_BINDING"):
        store.claim("post_comment", ARGS | {"body": "changed"}, proof)
    assert store.get_action("s", action["id"])["status"] == "INVALIDATED"
    with pytest.raises(DomainError):
        store.claim("post_comment", ARGS, proof)


def test_expiration_rejection_and_missing(store):
    expired = store.pending("s", "post_comment", ARGS, "Comment", -1)
    assert store.get_action("s", expired["id"])["status"] == "EXPIRED"
    with pytest.raises(DomainError, match="APPROVAL_EXPIRED"):
        store.decide("s", expired["id"], True)
    action = store.pending("s", "post_comment", ARGS, "Comment")
    assert store.pending("s", "post_comment", ARGS, "Comment")["id"] == action["id"]
    assert store.decide("s", action["id"], False) is None
    with pytest.raises(DomainError, match="ACTION_ALREADY_DECIDED"):
        store.decide("s", action["id"], True)
    with pytest.raises(DomainError):
        store.get_action("other", action["id"])
    with pytest.raises(DomainError):
        store.decide("s", "missing", False)
    with pytest.raises(DomainError, match="REQUIRE_CONFIRM"):
        store.claim("post_comment", ARGS, None)
    assert any(x["event"] == "REJECTED" for x in store.events("s"))


def test_expired_token(store):
    action, proof = prepare(store)
    with store.connection() as db:
        db.execute("UPDATE actions SET expires=? WHERE id=?", (time.time() - 1, action["id"]))
    with pytest.raises(DomainError, match="APPROVAL_EXPIRED"):
        store.claim("post_comment", ARGS, proof)


def test_concurrent_claim_and_duplicate_fingerprint(store):
    action, proof = prepare(store)

    def claim():
        try:
            return store.claim("post_comment", ARGS, proof)
        except DomainError:
            return "blocked"

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: claim(), range(5)))
    assert results.count(action["id"]) == 1
    other, other_proof = prepare(store, session="s2")
    with pytest.raises(DomainError, match="DUPLICATE_SUPPRESSED"):
        store.claim("post_comment", ARGS, other_proof)
    assert Store(store.path).get_action("s", action["id"])["status"] == "EXECUTING"
    assert store.get_action("s2", other["id"])["status"] == "DUPLICATE"


def test_budget_runs_and_transactions(store):
    assert store.consume("r", 1) == 1
    with pytest.raises(DomainError):
        store.consume("r", 1)
    store.save_run("s", "r", {"ok": True})
    assert store.get_run("s", "r") == {"ok": True}
    with pytest.raises(DomainError):
        store.get_run("other", "r")
    with pytest.raises(RuntimeError), store.transaction() as db:
        db.execute("INSERT INTO budgets VALUES('rollback',0)")
        raise RuntimeError()
    with store.connection() as db:
        assert db.execute("SELECT * FROM budgets WHERE id='rollback'").fetchone() is None


def test_config(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GITHUB_MODE", "mock")
    monkeypatch.setenv("MCP_URL", "http://127.0.0.1:8022/mcp")
    assert Settings.from_env().mcp_url.endswith("/mcp")
    monkeypatch.setenv("MCP_URL", "https://attacker.test/mcp")
    with pytest.raises(DomainError):
        Settings.from_env()
    monkeypatch.setenv("GITHUB_MODE", "invalid")
    with pytest.raises(DomainError):
        Settings.from_env()
