from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


TICKET_ID_PATTERN = r"^[A-Z]+-\d+$"


class JiraAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    type: Optional[str] = None
    size: Optional[int] = None
    download_url: Optional[str] = None
    content: Optional[str] = None


class JiraIssueResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    summary: Optional[str] = None
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    issue_type: Optional[str] = None
    assignee: Optional[str] = None
    reporter: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    attachments: List[JiraAttachment] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JiraSearchMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    summary: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None


class JiraLookupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    query: str
    normalized_input: str
    is_ticket_id: bool
    data: Optional[JiraIssueResponse] = None
    matches: List[JiraSearchMatch] = Field(default_factory=list)
    message: Optional[str] = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class JiraToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_key: str = Field(pattern=TICKET_ID_PATTERN)


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class JiraToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: Optional[JiraIssueResponse] = None
    error: Optional[ToolError] = None
