from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JiraComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author: Optional[str] = None
    body: Optional[str] = None
    created: Optional[str] = None


class JiraAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: Optional[str] = None
    size: Optional[int] = None
    mimeType: Optional[str] = None
    download_url: Optional[str] = None


class JiraIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_key: str
    summary: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    issue_type: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    reporter: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    comments: List[JiraComment] = Field(default_factory=list)
    attachments: List[JiraAttachment] = Field(default_factory=list)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class JiraToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_key: str = Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$")


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class JiraToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: Optional[JiraIssueResponse] = None
    error: Optional[ToolError] = None
