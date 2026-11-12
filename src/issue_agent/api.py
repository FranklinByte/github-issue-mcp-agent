import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from issue_agent.agent import run_task
from issue_agent.client import connect
from issue_agent.config import Settings
from issue_agent.models import ActionDraft, StrictModel, TaskRequest
from issue_agent.security import DomainError, Policy, configure_logging, redact
from issue_agent.storage import Store

STATIC = Path(__file__).parent / "static"


class DecisionRequest(StrictModel):
    fingerprint: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store, policy = Store(settings.db_path), Policy(settings.allowlist)
    app = FastAPI(title="GitHub Issue MCP Agent", version="1.0.0")
    app.state.store = store
    app.state.settings = settings
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "web"]
    )
    slots = asyncio.Semaphore(4)

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and (
                urlsplit(origin).netloc != request.headers.get("host")
                or urlsplit(origin).scheme != request.url.scheme
            ):
                return JSONResponse({"error": "BLOCK_ORIGIN"}, status_code=403)
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or int(length) > 32768:
                return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)
            if len(await request.body()) > 32768:
                return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)
        response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "X-Frame-Options": "DENY",
            }
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status = 403 if exc.code.startswith(("BLOCK", "INVALID_SESSION", "CSRF")) else 409
        return JSONResponse({"error": exc.code}, status_code=status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "error": "BLOCK_INVALID_ARGUMENTS",
                "fields": [list(error["loc"]) for error in exc.errors()],
            },
            status_code=422,
        )

    def session_id(request: Request, *, write: bool = False) -> str:
        csrf = request.headers.get("x-csrf-token") if write else None
        if write and not csrf:
            raise DomainError("CSRF_REQUIRED")
        return store.require_session(request.cookies.get("issue_session"), csrf)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        try:
            with store.connection() as db:
                db.execute("SELECT 1")
            async with connect(settings, uuid.uuid4().hex) as gateway:
                return JSONResponse(
                    {
                        "status": "ready",
                        "tools": len(gateway.tools),
                        "protocol": gateway.client.protocol_version,
                    }
                )
        except Exception:
            return JSONResponse(
                {"status": "unavailable", "error": "MCP_NOT_READY"}, status_code=503
            )

    @app.get("/api/session")
    async def session(request: Request) -> JSONResponse:
        cookie, csrf = store.session(request.cookies.get("issue_session"))
        response = JSONResponse(
            {
                "csrf": csrf,
                "repositories": list(settings.allowlist),
                "github_mode": settings.github_mode,
                "transport": "streamable-http" if settings.mcp_url else "stdio",
                "approval_ttl_seconds": settings.approval_ttl,
            }
        )
        response.set_cookie(
            "issue_session", cookie, httponly=True, samesite="strict", max_age=86400
        )
        return response

    @app.post("/api/tasks")
    async def task(payload: TaskRequest, request: Request) -> Any:
        session = session_id(request, write=True)
        async with slots:
            return await run_task(settings, store, session, payload)

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict[str, Any]:
        return store.get_run(session_id(request), run_id)

    @app.get("/api/actions")
    async def actions(request: Request) -> list[dict[str, Any]]:
        return store.list_actions(session_id(request))

    @app.post("/api/proposals")
    async def propose(payload: ActionDraft, request: Request) -> dict[str, Any]:
        session = session_id(request, write=True)
        args = policy.validate(payload.tool, payload.arguments)
        return store.pending(
            session, payload.tool, redact(args), redact(payload.impact), settings.approval_ttl
        )

    async def decide(
        action_id: str, payload: DecisionRequest, request: Request, approve: bool
    ) -> dict[str, Any]:
        session = session_id(request, write=True)
        action = store.get_action(session, action_id)
        if action["fingerprint"] != payload.fingerprint:
            store.audit(session, "BLOCK_REVIEW_HASH", {"action_id": action_id})
            raise DomainError("BLOCK_REVIEW_HASH")
        if not approve:
            store.decide(session, action_id, False)
            return {"action": store.get_action(session, action_id), "trace": []}
        # Discover before issuing a one-time credential. Approval is never a model tool.
        async with connect(settings, uuid.uuid4().hex) as gateway:
            proof = store.decide(session, action_id, True)
            try:
                await gateway.call(action["tool"], action["arguments"], proof)
            except DomainError as exc:
                store.audit(
                    session, "EXECUTION_RESPONSE_ERROR", {"action_id": action_id, "error": exc.code}
                )
            store.audit(
                session,
                "MCP_WRITE_TRACE",
                {
                    "action_id": action_id,
                    "trace": [t.model_dump(mode="json") for t in gateway.trace],
                },
            )
            return {
                "action": store.get_action(session, action_id),
                "trace": [t.model_dump(mode="json") for t in gateway.trace],
            }

    @app.post("/api/actions/{action_id}/approve")
    async def approve(action_id: str, payload: DecisionRequest, request: Request) -> dict[str, Any]:
        return await decide(action_id, payload, request, True)

    @app.post("/api/actions/{action_id}/reject")
    async def reject(action_id: str, payload: DecisionRequest, request: Request) -> dict[str, Any]:
        return await decide(action_id, payload, request, False)

    @app.get("/api/audit")
    async def audit(request: Request) -> list[dict[str, Any]]:
        return store.events(session_id(request))

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def load_env_file(path: Path) -> None:
    """Seed missing environment variables from a local, git-ignored ``.env``.

    Existing variables always win, so Compose and CI configuration is unchanged.
    """

    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_env_file(Path(__file__).resolve().parents[2] / ".env")
    configure_logging()
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.web_port, log_level="warning")


if __name__ == "__main__":
    main()
