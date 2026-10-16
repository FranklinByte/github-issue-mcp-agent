import asyncio
import json
import os
from typing import Any

import httpx

from issue_agent.config import Settings
from issue_agent.mock_github import MockGitHub
from issue_agent.security import WRITE_TOOLS, DomainError, redact
from issue_agent.storage import Store

API_BASE = "https://api.github.com"
SAFE_RATE_HEADERS = {
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "retry-after",
}


class GitHubAdapter:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        *,
        token: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings, self.store = settings, store
        self._token = token
        if settings.github_mode == "mock" and transport is None:
            transport = httpx.MockTransport(MockGitHub(store, settings.allowlist))
        if settings.github_mode == "real" and not token:
            raise DomainError("GITHUB_TOKEN_MISSING")
        self.transport = transport

    @classmethod
    def for_server(cls, settings: Settings, store: Store) -> "GitHubAdapter":
        # Only the MCP server invokes this factory; the web process never reads the PAT.
        return cls(
            settings,
            store,
            token=os.getenv("GITHUB_TOKEN", "") if settings.github_mode == "real" else "",
        )

    def clean(self, value: Any) -> Any:
        return redact(value, (self._token,))

    async def execute(self, tool: str, arguments: dict[str, Any], run_id: str) -> dict[str, Any]:
        repo = arguments["repo"]
        path, method = f"/repos/{repo}", "GET"
        params: dict[str, str | int] = {}
        body: dict[str, Any] | None = None
        if tool in {"get_issue", "get_issue_comments", "add_labels", "post_comment"}:
            path += f"/issues/{arguments['issue_number']}"
        if tool in {"list_open_issues", "create_issue"}:
            path += "/issues"
        if tool == "list_open_issues":
            params["state"] = "open"
        if tool in {"get_issue_comments", "post_comment"}:
            path += "/comments"
        if tool in {"list_labels", "add_labels"}:
            path += "/labels"
        if tool == "search_issues":
            path = "/search/issues"
            params["q"] = f"{arguments['query']} repo:{repo} is:issue"
        if "page" in arguments:
            params.update(page=arguments["page"], per_page=arguments["per_page"])
        if tool in WRITE_TOOLS:
            method = "POST"
            body = {k: v for k, v in arguments.items() if k not in {"repo", "issue_number"}}
        result = await self.request(method, path, params, body, run_id)
        data = result["data"]
        upstream_has_next = result.pop("_has_next_page", None)
        if tool == "search_issues":
            data = data.get("items", []) if isinstance(data, dict) else []
        raw_count = len(data) if isinstance(data, list) else 0
        if isinstance(data, list):
            data = [v for v in data if isinstance(v, dict) and "pull_request" not in v]
        if tool == "get_issue" and isinstance(data, dict) and "pull_request" in data:
            raise DomainError("BLOCK_PULL_REQUEST")
        result["data"] = self.clean(data)
        if "page" in arguments:
            # PR filtering changes the visible count, not the upstream page size.
            # Use Link metadata when present; Mock responses omit it, so retain
            # a conservative raw-page fallback. Never follow an upstream URL.
            has_more = (
                upstream_has_next
                if isinstance(upstream_has_next, bool)
                else raw_count == arguments["per_page"]
            )
            result["next_page"] = (
                arguments["page"] + 1 if has_more and arguments["page"] < 3 else None
            )
            result["truncated"] = has_more
        result["untrusted"] = True
        return result

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, str | int],
        body: dict[str, Any] | None,
        run_id: str,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "student-issue-mcp-agent/1.0",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        write = method != "GET"
        attempts = 1 if write else 3
        async with httpx.AsyncClient(
            base_url=API_BASE,
            headers=headers,
            transport=self.transport,
            timeout=self.settings.github_timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for attempt in range(attempts):
                used = self.store.consume(run_id, self.settings.request_budget)
                try:
                    async with client.stream(method, path, params=params, json=body) as response:
                        rate = {
                            k: v
                            for k, v in response.headers.items()
                            if k in SAFE_RATE_HEADERS and v.isdigit() and len(v) <= 20
                        }
                        self.store.audit(
                            "system",
                            "GITHUB_RESPONSE",
                            {
                                "method": method,
                                "status": response.status_code,
                                "rate_limit": rate,
                                "requests_used": used,
                            },
                        )
                        status = response.status_code
                        if status >= 500:
                            if not write and attempt + 1 < attempts:
                                await asyncio.sleep(self.settings.retry_delay * (2**attempt))
                                continue
                            raise DomainError("GITHUB_5XX", uncertain=write)
                        if status == 429 or (
                            status == 403
                            and (rate.get("x-ratelimit-remaining") == "0" or "retry-after" in rate)
                        ):
                            raise DomainError("GITHUB_RATE_LIMIT")
                        if status in {401, 403, 404, 409, 422}:
                            raise DomainError(f"GITHUB_{status}")
                        if not 200 <= status < 300:
                            raise DomainError("GITHUB_UNEXPECTED_STATUS", uncertain=write)
                        buffer = bytearray()
                        async for chunk in response.aiter_bytes():
                            buffer.extend(chunk)
                            if len(buffer) > self.settings.response_limit:
                                raise DomainError("GITHUB_RESPONSE_TOO_LARGE", uncertain=write)
                        try:
                            data = json.loads(buffer)
                        except (ValueError, UnicodeDecodeError) as exc:
                            raise DomainError("GITHUB_INVALID_JSON", uncertain=write) from exc
                        if not isinstance(data, (dict, list)):
                            raise DomainError("GITHUB_INVALID_RESPONSE", uncertain=write)
                        return {
                            "data": data,
                            "rate_limit": rate,
                            "requests_used": used,
                            "_has_next_page": "next" in response.links
                            if "link" in response.headers
                            else None,
                        }
                except httpx.TransportError as exc:
                    if not write and attempt + 1 < attempts:
                        await asyncio.sleep(self.settings.retry_delay * (2**attempt))
                        continue
                    code = (
                        "GITHUB_TIMEOUT"
                        if isinstance(exc, httpx.TimeoutException)
                        else "GITHUB_NETWORK"
                    )
                    raise DomainError(code, uncertain=write) from exc
        raise DomainError("GITHUB_RETRY_EXHAUSTED")
