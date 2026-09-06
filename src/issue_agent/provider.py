import json
import os
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from issue_agent.security import DomainError, redact


class Provider(Protocol):
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, final: bool = False
    ) -> dict[str, Any]: ...


class CompatibleProvider:
    """Minimal Chat Completions adapter; no credential appears in messages or traces."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = os.getenv("MODEL_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("MODEL_NAME", "")
        self._key = os.getenv("MODEL_API_KEY", "")
        url = urlsplit(self.base_url)
        if (
            (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"})
            )
            or url.username
            or url.query
            or url.fragment
        ):
            raise DomainError("INVALID_PROVIDER_URL")
        if not self.model or not self._key:
            raise DomainError("PROVIDER_NOT_CONFIGURED")
        self.transport = transport

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, final: bool = False
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_completion_tokens": 2500,
        }
        if tools and not final:
            payload.update(tools=tools, tool_choice="auto", parallel_tool_calls=False)
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    "POST",
                    self.base_url + "/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._key}"},
                ) as response:
                    if response.status_code != 200:
                        raise DomainError("PROVIDER_UNAVAILABLE")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 262_144:
                            raise DomainError("PROVIDER_RESPONSE_TOO_LARGE")
                    result = json.loads(data)
                    if not isinstance(result, dict):
                        raise DomainError("PROVIDER_INVALID_RESPONSE")
                    return dict(redact(result, (self._key,)))
        except (httpx.TransportError, ValueError) as exc:
            raise DomainError("PROVIDER_UNAVAILABLE") from exc
