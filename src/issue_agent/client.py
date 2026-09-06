import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from jsonschema import Draft202012Validator
from mcp import Client, StdioServerParameters
from mcp.types import Tool

from issue_agent.config import Settings
from issue_agent.models import ApprovalProof, ToolTrace
from issue_agent.security import READ_TOOLS, DomainError, Policy, redact


class MCPGateway:
    def __init__(self, client: Client, policy: Policy, run_id: str) -> None:
        self.client, self.policy, self.run_id = client, policy, run_id
        self.tools: dict[str, Tool] = {}
        self.trace: list[ToolTrace] = []

    async def discover(self) -> None:
        cursor = None
        for _ in range(3):
            result = await self.client.list_tools(cursor=cursor)
            for tool in result.tools:
                self.tools[tool.name] = tool
            cursor = result.next_cursor
            if not cursor:
                break
        else:
            raise DomainError("MCP_DISCOVERY_BUDGET")
        if set(self.tools) != set(READ_TOOLS) | {"add_labels", "post_comment", "create_issue"}:
            raise DomainError("MCP_CATALOG_MISMATCH")

    def model_tools(self) -> list[dict[str, Any]]:
        exposed = []
        for name, tool in sorted(self.tools.items()):
            if name not in READ_TOOLS:
                continue
            schema = tool.input_schema
            args_schema = dict(schema["properties"]["args"])
            if "$ref" in args_schema:
                args_schema = dict(schema["$defs"][args_schema["$ref"].split("/")[-1]])
            if "$defs" in schema:
                args_schema["$defs"] = schema["$defs"]
            exposed.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.description,
                        "parameters": args_schema,
                    },
                }
            )
        return exposed

    async def call(
        self, name: str, arguments: dict[str, Any], proof: ApprovalProof | None = None
    ) -> dict[str, Any]:
        start = time.perf_counter()
        permission = self.policy.decide(name, arguments)
        result: dict[str, Any] = {}
        try:
            args = self.policy.validate(name, arguments)
            if name not in self.tools:
                raise DomainError("BLOCK_UNKNOWN_TOOL")
            payload = {"args": args, "run_id": self.run_id}
            if proof:
                payload["authorization"] = proof.model_dump()
            if not Draft202012Validator(self.tools[name].input_schema).is_valid(payload):
                raise DomainError("BLOCK_MCP_SCHEMA")
            response = await self.client.call_tool(name, payload, read_timeout_seconds=40)
            if response.is_error or response.structured_content is None:
                raise DomainError("MCP_TOOL_ERROR")
            result = dict(response.structured_content)
            if not result.get("ok"):
                raise DomainError(str(result.get("error", "MCP_TOOL_ERROR")))
            return result
        except DomainError as exc:
            result = result or {"ok": False, "error": exc.code}
            raise
        except Exception as exc:
            result = {"ok": False, "error": "MCP_TRANSPORT_ERROR"}
            raise DomainError("MCP_TRANSPORT_ERROR") from exc
        finally:
            self.trace.append(
                ToolTrace(
                    tool=name,
                    arguments=redact(arguments),
                    permission=permission,
                    status="ok" if result.get("ok") else "error",
                    duration_ms=round((time.perf_counter() - start) * 1000, 3),
                    result=redact(result),
                )
            )


@asynccontextmanager
async def connect(
    settings: Settings, run_id: str, *, legacy: bool = False
) -> AsyncIterator[MCPGateway]:
    target: str | StdioServerParameters
    if settings.mcp_url:
        target = settings.mcp_url
    else:
        if settings.github_mode != "mock":
            raise DomainError("REAL_MODE_REQUIRES_SEPARATE_MCP_SERVER")
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "HOME",
                "VIRTUAL_ENV",
                "COVERAGE_PROCESS_START",
                "COVERAGE_RCFILE",
                "COVERAGE_FILE",
            }
            or key.startswith("COV_CORE_")
        }
        env.update(
            DATA_DIR=str(settings.data_dir.resolve()),
            GITHUB_MODE="mock",
            REPO_ALLOWLIST=",".join(settings.allowlist),
            PYTHONUNBUFFERED="1",
        )
        target = StdioServerParameters(
            command=sys.executable, args=["-m", "issue_agent.server"], env=env
        )
    body_error: Exception | None = None
    try:
        async with Client(
            target, mode="legacy" if legacy else "auto", read_timeout_seconds=40
        ) as client:
            try:
                gateway = MCPGateway(client, Policy(settings.allowlist), run_id)
                await gateway.discover()
                yield gateway
            except Exception as exc:
                # Exit SDK task groups normally, then re-raise the original business error.
                body_error = exc
    except Exception as exc:
        raise DomainError("MCP_TRANSPORT_ERROR") from exc
    if body_error is not None:
        raise body_error
