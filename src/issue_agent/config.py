import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from issue_agent.security import DomainError, Policy


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    allowlist: tuple[str, ...] = ("student-lab/course-project",)
    github_mode: Literal["mock", "real"] = "mock"
    mcp_url: str | None = None
    approval_ttl: int = 300
    request_budget: int = 24
    response_limit: int = 262_144
    github_timeout: float = 10.0
    retry_delay: float = 0.1
    web_port: int = 8021

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("GITHUB_MODE", "mock")
        if mode not in {"mock", "real"}:
            raise DomainError("INVALID_GITHUB_MODE")
        url = os.getenv("MCP_URL") or None
        if url:
            parsed = urlsplit(url)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "mcp"}
                or parsed.path != "/mcp"
                or parsed.username
                or parsed.query
                or parsed.fragment
            ):
                raise DomainError("INVALID_LOCAL_MCP_URL")
        settings = cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            allowlist=tuple(
                x.strip()
                for x in os.getenv("REPO_ALLOWLIST", "student-lab/course-project").split(",")
                if x.strip()
            ),
            github_mode="real" if mode == "real" else "mock",
            mcp_url=url,
            web_port=int(os.getenv("WEB_PORT", "8021")),
        )
        Policy(settings.allowlist)
        return settings

    @property
    def db_path(self) -> Path:
        return self.data_dir / "agent.sqlite3"
