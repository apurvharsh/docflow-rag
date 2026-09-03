"""Response models for API endpoints."""

from pydantic import BaseModel


class LoginResponse(BaseModel):
    """Authentication response with token."""
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool = False


class AccessContext(BaseModel):
    """Current user's access context."""
    user_id: str
    tenant_id: str
    is_org_admin: bool
    sensitivity_clearance: int
    accessible_projects: list[str]


class ProjectSummary(BaseModel):
    """Project listing summary."""
    project_id: str
    project_name: str
    document_count: int


class DocumentSummary(BaseModel):
    """Document in project listing."""
    document_id: str
    project_id: str
    filename: str
    stage: str
    doc_type: str
    workflow_state: str | None = None


class DocumentDetailSummary(BaseModel):
    """Full document details."""
    document_id: str
    project_id: str
    filename: str
    stage: str
    doc_type: str
    sensitivity_level: int
    chunk_count: int
    created_at: str
    workflow_state: str | None = None


class UploadResponse(BaseModel):
    """Document upload response."""
    document_id: str
    filename: str
    stored_path: str
    chunk_count: int


class BatchUploadResponse(BaseModel):
    """Batch upload response."""
    project_id: str
    documents: list[UploadResponse]
    total_chunks: int


class SearchResult(BaseModel):
    """Single search result chunk."""
    document_id: str
    section_title: str
    chunk_text: str
    score: float


class AskResponse(BaseModel):
    """AI question-answering response."""
    answer: str
    sources: list[SearchResult]


class AuditLogEntry(BaseModel):
    """Audit log entry."""
    log_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str | None
    details: str | None
    timestamp: str


class GenerateOutlineResponse(BaseModel):
    """Drafting agent outline response."""
    outline: str
    stage: str


class GapAnalysisResponse(BaseModel):
    """Gap-detection agent analysis response."""
    project_id: str
    total_gaps: int
    gaps_by_stage: dict
    gap_report: str


class FollowupSuggestions(BaseModel):
    """Query agent follow-up suggestions."""
    followup_questions: list[str]


class PendingApprovals(BaseModel):
    """Pending document approvals."""
    document_id: str
    filename: str
    stage: str
    doc_type: str
    created_at: str
    created_by: str
