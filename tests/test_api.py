import httpx

from issue_agent.api import create_app

REPO = "student-lab/course-project"


async def test_api_end_to_end(settings):
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost"
    ) as client:
        assert (await client.get("/")).status_code == 200
        assert (await client.get("/health")).json()["status"] == "ok"
        assert (await client.get("/ready")).json()["tools"] == 9
        assert (await client.get("/api/actions")).status_code == 403
        session = (await client.get("/api/session")).json()
        headers = {"x-csrf-token": session["csrf"]}
        payload = {"repo": REPO, "issue": 1, "task": "Triage", "allow_writes": True}
        assert (await client.post("/api/tasks", json=payload)).status_code == 403
        assert (
            await client.post(
                "/api/tasks", json=payload, headers=headers | {"origin": "https://evil.test"}
            )
        ).status_code == 403
        invalid = await client.post(
            "/api/tasks", json=payload | {"unknown": "ghp_secret"}, headers=headers
        )
        assert invalid.status_code == 422 and "ghp_secret" not in invalid.text
        result = (await client.post("/api/tasks", json=payload, headers=headers)).json()
        assert result["status"] == "awaiting_approval", result
        assert (await client.get(f"/api/runs/{result['run_id']}")).json()["run_id"] == result[
            "run_id"
        ]
        actions = (await client.get("/api/actions")).json()
        action = actions[0]
        review = {"fingerprint": action["fingerprint"]}
        url = f"/api/actions/{action['id']}/approve"
        assert (
            await client.post(url, json={"fingerprint": "0" * 64}, headers=headers)
        ).status_code == 403
        executed = (await client.post(url, json=review, headers=headers)).json()
        assert executed["action"]["status"] == "SUCCEEDED", executed
        assert len(executed["trace"]) == 1
        assert (await client.post(url, json=review, headers=headers)).status_code == 409
        other = actions[1]
        rejected = await client.post(
            f"/api/actions/{other['id']}/reject",
            json={"fingerprint": other["fingerprint"]},
            headers=headers,
        )
        assert rejected.json()["action"]["status"] == "REJECTED"
        events = (await client.get("/api/audit")).json()
        assert {"APPROVED", "REJECTED", "SUCCEEDED"}.issubset({e["event"] for e in events})
        assert "token_hash" not in str(events)
        assert (
            "frame-ancestors 'none'" in (await client.get("/")).headers["content-security-policy"]
        )
        proposal = {
            "tool": "create_issue",
            "arguments": {"repo": REPO, "title": "Test", "body": "Details"},
            "impact": "Create",
        }
        assert (
            await client.post("/api/proposals", json=proposal, headers=headers)
        ).status_code == 200
        assert (
            await client.post("/api/tasks", content="x" * 32769, headers=headers)
        ).status_code == 413


async def test_api_session_isolation(settings):
    app = create_app(settings)
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as a,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as b,
    ):
        sa = (await a.get("/api/session")).json()
        sb = (await b.get("/api/session")).json()
        proposal = {
            "tool": "post_comment",
            "arguments": {"repo": REPO, "issue_number": 1, "body": "Hi"},
            "impact": "Comment",
        }
        action = (
            await a.post("/api/proposals", json=proposal, headers={"x-csrf-token": sa["csrf"]})
        ).json()
        response = await b.post(
            f"/api/actions/{action['id']}/approve",
            json={"fingerprint": action["fingerprint"]},
            headers={"x-csrf-token": sb["csrf"]},
        )
        assert response.status_code == 409
        assert (await b.get("/api/actions")).json() == []
