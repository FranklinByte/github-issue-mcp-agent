import hashlib
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from issue_agent.models import (
    CommentArgs,
    CommentsArgs,
    CreateArgs,
    IssueArgs,
    LabelsArgs,
    PageArgs,
    Permission,
    RepoArgs,
    SearchArgs,
)

READ_TOOLS: dict[str, type[RepoArgs]] = {
    "get_repository": RepoArgs,
    "get_issue": IssueArgs,
    "list_open_issues": PageArgs,
    "search_issues": SearchArgs,
    "list_labels": PageArgs,
    "get_issue_comments": CommentsArgs,
}
WRITE_TOOLS: dict[str, type[RepoArgs]] = {
    "add_labels": LabelsArgs,
    "post_comment": CommentArgs,
    "create_issue": CreateArgs,
}
TOOL_MODELS = READ_TOOLS | WRITE_TOOLS


class DomainError(Exception):
    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(tool: str, arguments: dict[str, Any]) -> str:
    return digest(canonical({"tool": tool, "arguments": arguments}))


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]"
            if str(k).lower()
            in {"token", "authorization", "approval_token", "api_key", "session_id", "csrf"}
            else redact(v, secrets)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(
            r"(?i)(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9]+|"
            r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]+)",
            "[REDACTED]",
            value,
        )
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return canonical({"level": record.levelname, "event": redact(record.getMessage())})


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)


class Policy:
    def __init__(self, allowlist: tuple[str, ...]) -> None:
        self.allowlist = {RepoArgs(repo=repo).repo for repo in allowlist}

    def validate(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in TOOL_MODELS:
            raise DomainError("BLOCK_UNKNOWN_TOOL")
        try:
            validated = TOOL_MODELS[tool].model_validate(arguments).model_dump()
        except ValidationError as exc:
            raise DomainError("BLOCK_INVALID_ARGUMENTS") from exc
        if validated["repo"] not in self.allowlist:
            raise DomainError("BLOCK_REPOSITORY")
        return validated

    def decide(self, tool: str, arguments: dict[str, Any]) -> Permission:
        try:
            self.validate(tool, arguments)
        except DomainError:
            return Permission.BLOCK
        return Permission.ALLOW if tool in READ_TOOLS else Permission.REQUIRE_CONFIRM


def parse_issue(repo: str, value: int | str) -> int:
    if isinstance(value, str) and value.startswith("https://"):
        url = urlsplit(value)
        parts = url.path.strip("/").split("/")
        if (
            url.netloc != "github.com"
            or url.query
            or url.fragment
            or len(parts) != 4
            or parts[2] != "issues"
            or "/".join(parts[:2]).lower() != repo.lower()
        ):
            raise DomainError("BLOCK_ISSUE_URL")
        value = parts[3]
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,10}", value):
            raise DomainError("BLOCK_ISSUE_NUMBER")
        value = int(value)
    try:
        return IssueArgs(repo=repo, issue_number=value).issue_number
    except ValidationError as exc:
        raise DomainError("BLOCK_ISSUE_NUMBER") from exc
