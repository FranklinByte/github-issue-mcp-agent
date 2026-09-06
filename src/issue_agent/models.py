from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RepoName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$")]
IssueNumber = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RepoArgs(StrictModel):
    repo: RepoName

    @field_validator("repo")
    @classmethod
    def normalize_repo(cls, value: str) -> str:
        if value.split("/")[1] in {".", ".."}:
            raise ValueError("Invalid repository")
        return value.lower()


class IssueArgs(RepoArgs):
    issue_number: IssueNumber


class PageArgs(RepoArgs):
    page: Annotated[int, Field(ge=1, le=3)] = 1
    per_page: Annotated[int, Field(ge=1, le=30)] = 20


class CommentsArgs(IssueArgs):
    page: Annotated[int, Field(ge=1, le=3)] = 1
    per_page: Annotated[int, Field(ge=1, le=30)] = 20


class SearchArgs(PageArgs):
    query: Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[\w\s.-]+$")]


class LabelsArgs(IssueArgs):
    labels: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=50)]], Field(min_length=1, max_length=5)
    ]


class CommentArgs(IssueArgs):
    body: Annotated[str, Field(min_length=1, max_length=6000)]


class CreateArgs(RepoArgs):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=6000)]


class ApprovalProof(StrictModel):
    action_id: str
    session_id: str
    token: str


class Permission(StrEnum):
    ALLOW = "ALLOW"
    REQUIRE_CONFIRM = "REQUIRE_CONFIRM"
    BLOCK = "BLOCK"


class ActionDraft(StrictModel):
    tool: Literal["add_labels", "post_comment", "create_issue"]
    arguments: dict[str, Any]
    impact: Annotated[str, Field(min_length=1, max_length=500)]


class TriageProposal(StrictModel):
    summary: Annotated[str, Field(min_length=1, max_length=2000)]
    issue_type: Literal["bug", "feature", "question", "other"]
    suggested_labels: Annotated[list[str], Field(max_length=5)] = []
    missing_information: Annotated[list[str], Field(max_length=10)] = []
    related_issues: Annotated[list[dict[str, Any]], Field(max_length=10)] = []
    reply_draft: Annotated[str, Field(max_length=6000)] = ""
    actions: Annotated[list[ActionDraft], Field(max_length=3)] = []


class TaskRequest(StrictModel):
    repo: RepoName
    issue: int | str
    task: Annotated[str, Field(min_length=1, max_length=2000)]
    allow_writes: bool = False
    mode: Literal["offline", "provider"] = "offline"


class ToolTrace(StrictModel):
    tool: str
    arguments: dict[str, Any]
    permission: Permission
    status: str
    duration_ms: float
    result: dict[str, Any]


class TaskResult(StrictModel):
    run_id: str
    mode: str
    github_mode: str
    status: str
    proposal: TriageProposal | None = None
    pending_actions: list[dict[str, Any]] = []
    trace: list[ToolTrace] = []
    rounds: int = 0
    provider_responses: int = 0
    protocol_version: str | None = None
    error: str | None = None
    usage: dict[str, int] | None = None
    cost_usd: float | None = None
