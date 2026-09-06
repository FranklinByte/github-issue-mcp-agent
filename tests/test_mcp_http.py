import asyncio
import socket

import httpx
import uvicorn
from mcp import Client

from issue_agent.server import http_app


async def test_real_loopback_http(settings):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(http_app(settings), log_level="critical", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        async with Client(f"http://127.0.0.1:{port}/mcp") as client:
            assert client.protocol_version == "2026-07-28"
            assert len((await client.list_tools()).tools) == 9
            result = await client.call_tool(
                "get_issue", {"args": {"repo": "student-lab/course-project", "issue_number": 1}}
            )
            assert result.structured_content["data"]["number"] == 1
            for name, args in [
                ("get_issue", {"repo": "student-lab/course-project", "issue_number": "1"}),
                ("get_repository", {"repo": "evil/repo"}),
                ("delete_issue", {}),
                (
                    "get_repository",
                    {"repo": "student-lab/course-project", "url": "http://localhost"},
                ),
            ]:
                result = await client.call_tool(name, {"args": args})
                assert result.is_error or result.structured_content["ok"] is False
        async with httpx.AsyncClient() as client:
            assert (await client.get(f"http://127.0.0.1:{port}/health")).status_code == 200
            denied = await client.post(
                f"http://127.0.0.1:{port}/mcp", headers={"host": "attacker.test"}, json={}
            )
            assert denied.status_code in {400, 403, 421}
    finally:
        server.should_exit = True
        await task
        sock.close()
