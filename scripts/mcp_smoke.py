"""Official SDK, real process transport verification; never touches real GitHub."""

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

from issue_agent.client import connect
from issue_agent.config import Settings
from issue_agent.security import DomainError
from issue_agent.storage import Store


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(data_dir=Path(directory))
        store = Store(settings.db_path)
        evidence = {}
        async with connect(settings, uuid.uuid4().hex) as gateway:
            evidence["protocol"] = gateway.client.protocol_version
            evidence["capabilities"] = gateway.client.server_capabilities.model_dump(mode="json")
            evidence["tools"] = [
                tool.model_dump(mode="json", by_alias=True) for tool in gateway.tools.values()
            ]
            evidence["read"] = await gateway.call(
                "get_issue", {"repo": settings.allowlist[0], "issue_number": 1}
            )
            args = {
                "repo": settings.allowlist[0],
                "issue_number": 1,
                "body": "Official SDK smoke test",
            }
            try:
                await gateway.call("post_comment", args)
                raise AssertionError("Unapproved write was accepted")
            except DomainError as exc:
                assert exc.code == "REQUIRE_CONFIRM"
                evidence["unapproved_write"] = exc.code
            action = store.pending("test-session", "post_comment", args, "Add one mock comment")
            proof = store.decide("test-session", action["id"], True)
            evidence["approved_write"] = await gateway.call("post_comment", args, proof)
            try:
                await gateway.call("post_comment", args, proof)
                raise AssertionError("Repeated write was accepted")
            except DomainError as exc:
                evidence["repeated_write"] = exc.code
        async with connect(settings, uuid.uuid4().hex, legacy=True) as gateway:
            evidence["legacy_protocol"] = gateway.client.protocol_version
            evidence["legacy_read"] = await gateway.call(
                "get_repository", {"repo": settings.allowlist[0]}
            )
        output = Path("artifacts/mcp-smoke.json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in evidence.items() if k != "tools"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
