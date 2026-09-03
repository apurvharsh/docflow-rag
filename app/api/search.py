"""FastAPI route: search_documents — wires auth -> filter -> hybrid search.

This is the shape the LangGraph agent's search_documents tool should call
into. summarize_stage and check_gaps should follow the same pattern:
resolve UserContext -> build_access_filter -> query, never bypassing
build_access_filter.
"""

from pathlib import Path
from uuid import uuid4
import hmac
import json
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from qdrant_client import QdrantClient, models

from app.config import settings
from app.agent_runtime import create_default_state, handle_cli_message
from app.auth import _hash_password, authenticate, create_oauth_state, create_token, exchange_google_code, google_authorization_url, google_is_configured, user_from_token, validate_oauth_state
from app.telemetry import PerformanceMetrics
from app.database import (
    create_user, get_user_by_provider_subject, get_user_by_username, initialize_database,
    list_all_documents as database_list_all_documents, list_documents as database_list_documents,
    list_projects as database_list_projects, record_document, get_valid_stages, get_user_role,
    set_user_role, get_document_workflow_state, approve_document, reject_document, audit_log,
    get_audit_log, get_user_by_id, get_user_access_context, get_document, get_project, list_users,
    link_user_provider,
    submit_document, update_user_access, create_project, create_note, list_notes
)
from app.authorization import can_view_document, require_action, require_document_action, require_project, require_tenant
from app.ingestion.chunking import ParsedSection, chunk_document
from app.ingestion.document_text import extract_text
from app.ingestion.indexing import index_chunks, update_document_workflow_state
from app.models.schema import UserContext
from app.retrieval.access_filter import build_access_filter
from app.retrieval.embeddings import embed_dense, embed_sparse, generate_answer
from app.retrieval.hybrid_search import hybrid_search

app = FastAPI(title="DocFlow AI — RAG Search")
initialize_database()
bearer = HTTPBearer(auto_error=False)
UPLOADS_DIR = Path(settings.uploads_path)
UI_DIR = Path(__file__).parent.parent / "ui"
UI_FILE = UI_DIR / "index.html"


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(UI_FILE)


@app.get("/react-app.js", include_in_schema=False)
def react_app():
    return FileResponse(UI_DIR / "react-app.js", media_type="application/javascript")


@app.get("/agent", include_in_schema=False)
def agent_console():
    return FileResponse(Path(__file__).parent.parent / "ui" / "agent_chat.html")


@app.post("/agent/chat", include_in_schema=False)
def agent_chat(payload: dict):
    message = (payload or {}).get("message", "")
    state = (payload or {}).get("state") or create_default_state()
    result = handle_cli_message(message, state)
    return result


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}

_qdrant_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        if settings.qdrant_url:
            _qdrant_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        else:
            _qdrant_client = QdrantClient(path=settings.qdrant_path)
    return _qdrant_client


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UserContext:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return user_from_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UserContext:
    if credentials is not None and credentials.credentials:
        try:
            return user_from_token(credentials.credentials)
        except ValueError:
            pass
    raise HTTPException(status_code=401, detail="Authentication required")


class AccessContext(BaseModel):
    user_id: str
    username: str | None = None
    full_name: str | None = None
    organization: str | None = None
    team_name: str | None = None
    job_title: str | None = None
    tenant_id: str
    is_org_admin: bool
    role: str
    sensitivity_clearance: int
    accessible_projects: list[str]
    project_roles: dict[str, str] = Field(default_factory=dict)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool = False


class SignupRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=256)
    full_name: str = Field(min_length=2, max_length=120)
    organization: str = Field(min_length=2, max_length=160)
    team_name: str = Field(min_length=2, max_length=120)
    job_title: str = Field(min_length=2, max_length=120)
    manager_email: str | None = Field(default=None, max_length=254)


@app.post("/signup", response_model=LoginResponse, status_code=201)
def signup(request: SignupRequest):
    email = request.email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if email == settings.auth_username.lower() or get_user_by_username(email):
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    salt = settings.auth_secret.encode()[:16].ljust(16, b"0")
    user = create_user(username=email, password_hash=_hash_password(request.password, salt), provider="password", provider_subject=None, full_name=request.full_name.strip(), organization=request.organization.strip(), team_name=request.team_name.strip(), job_title=request.job_title.strip(), manager_email=request.manager_email.strip().lower() if request.manager_email else None)
    return LoginResponse(access_token=create_token(subject=user["username"], user_id=user["user_id"]), is_new_user=True)


@app.post("/login", response_model=LoginResponse)
def login(request: LoginRequest):
    token = authenticate(request.email.strip().lower(), request.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return LoginResponse(access_token=token)


@app.post("/auth/demo", response_model=LoginResponse)
def demo_login():
    """Instant login endpoint for visitors and demo evaluators (admin access for full feature exploration)."""
    demo_email = "demo.user@docflow.ai"
    user = get_user_by_username(demo_email)
    if user is None:
        user = create_user(
            username=demo_email,
            password_hash=None,
            provider="demo",
            provider_subject="demo-user",
            full_name="Demo User",
            organization="DocFlow Community",
            team_name="Engineering",
            job_title="Product Explorer",
        )
    # Return an admin token so demo users can see all features without permission issues
    return LoginResponse(access_token=create_token(subject=settings.auth_username, user_id=settings.dev_user_id))


@app.get("/auth/google/start", include_in_schema=False)
def google_start(request: Request, response: Response):
    if not google_is_configured():
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    state = create_oauth_state()
    response.set_cookie("google_oauth_state", state, httponly=True, secure=request.url.scheme == "https", samesite="lax", max_age=600)
    response.status_code = 307
    response.headers["location"] = google_authorization_url(state)
    return response


@app.get("/auth/google/callback", include_in_schema=False)
def google_callback(code: str, state: str, request: Request, response: Response):
    expected_state = request.cookies.get("google_oauth_state")
    if not validate_oauth_state(state) or (expected_state and not hmac.compare_digest(state, expected_state)):
        raise HTTPException(status_code=400, detail="Invalid Google sign-in state")
    try:
        identity = exchange_google_code(code)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    subject = identity["subject"]
    user = get_user_by_provider_subject("google", subject)
    if user is None:
        user = get_user_by_username(identity["email"])
        if user:
            link_user_provider(user["user_id"], "google", subject)
        else:
            try:
                user = create_user(username=identity["email"], password_hash=None, provider="google", provider_subject=subject, full_name=identity.get("name"))
            except Exception as exc:
                raise HTTPException(status_code=409, detail="Could not create Google account") from exc
    response.delete_cookie("google_oauth_state")
    response.status_code = 303
    response.headers["location"] = f"/?auth_token={create_token(subject=user['username'], user_id=user['user_id'])}"
    return response


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain text")
        return value.strip()


class SearchResult(BaseModel):
    document_id: str
    section_title: str
    chunk_text: str
    score: float


class UploadResponse(BaseModel):
    document_id: str
    filename: str
    stored_path: str
    chunk_count: int


class ProjectSummary(BaseModel):
    project_id: str
    project_name: str
    document_count: int


class CreateProjectRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    project_name: str = Field(min_length=1, max_length=160)


class NoteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20000)
    project_id: str | None = None


@app.get("/me", response_model=AccessContext)
def current_access_context(user: UserContext = Depends(get_current_user)):
    user_db = get_user_by_id(user.user_id) if user.user_id else None
    return AccessContext(
        user_id=user.user_id,
        username=user_db.get("username") if user_db else (settings.auth_username if user.is_org_admin else user.user_id),
        full_name=user_db.get("full_name") if user_db else ("Super Admin" if user.is_org_admin else None),
        organization=user_db.get("organization") if user_db else "DocFlow Enterprise",
        team_name=user_db.get("team_name") if user_db else ("Administration" if user.is_org_admin else None),
        job_title=user_db.get("job_title") if user_db else ("Platform Administrator" if user.is_org_admin else None),
        tenant_id=user.tenant_id,
        is_org_admin=user.is_org_admin,
        role=user.role,
        sensitivity_clearance=user.sensitivity_clearance,
        accessible_projects=sorted(user.project_roles),
        project_roles=user.project_roles,
    )


class DocumentSummary(BaseModel):
    document_id: str
    project_id: str
    filename: str
    stage: str
    doc_type: str
    sensitivity_level: int
    chunk_count: int
    created_at: str
    uploaded_by: str | None = None
    workflow_state: str | None = None


class DocumentDetailSummary(BaseModel):
    document_id: str
    project_id: str
    project_name: str | None = None
    filename: str
    stored_path: str | None = None
    stage: str
    doc_type: str
    sensitivity_level: int
    chunk_count: int
    created_at: str
    uploaded_by: str | None = None
    workflow_state: str | None = None


@app.get("/projects", response_model=list[ProjectSummary])
def list_projects(
    user: UserContext = Depends(get_current_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """List project records visible to the current user."""
    _backfill_database_from_vectors(client, user.tenant_id)
    projects = database_list_projects(user.tenant_id)
    if user.is_org_admin:
        return projects
    return [project for project in projects if project["project_id"] in user.project_roles]


@app.post("/projects", response_model=ProjectSummary, status_code=201)
def create_project_endpoint(
    request: CreateProjectRequest,
    user: UserContext = Depends(get_current_user),
):
    """Create a personal project and grant its creator Member access."""
    if get_project(user.tenant_id, request.project_id):
        raise HTTPException(status_code=409, detail="Project ID already exists")
    try:
        project = create_project(user.tenant_id, request.project_id, request.project_name.strip(), user.user_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Project could not be created") from exc
    audit_log(user.tenant_id, user.user_id, "CREATE_PROJECT", "project", request.project_id)
    return project


def _backfill_database_from_vectors(client: QdrantClient, tenant_id: str) -> None:
    """Register pre-database Qdrant documents so existing data remains visible."""
    collection = f"tenant_{tenant_id}"
    if not client.collection_exists(collection):
        return
    points, _ = client.scroll(collection_name=collection, limit=10000, with_payload=True)
    documents: dict[str, dict] = {}
    for point in points:
        payload = point.payload or {}
        document_id = payload.get("document_id")
        if document_id and document_id not in documents:
            documents[document_id] = {
                "project_id": payload.get("project_id", "unknown"),
                "stage": payload.get("stage", "Unknown"),
                "doc_type": payload.get("doc_type", "Unknown"),
                "filename": payload.get("section_title", document_id),
                "sensitivity_level": payload.get("sensitivity_level", 1),
                "chunk_count": 0,
            }
        if document_id:
            documents[document_id]["chunk_count"] += 1
    for document_id, document in documents.items():
        record_document(
            tenant_id=tenant_id,
            project_name=document["project_id"],
            document_id=document_id,
            stored_path="",
            **document,
        )


@app.get("/projects/{project_id}/documents", response_model=list[DocumentSummary])
def list_project_documents(
    project_id: str,
    user: UserContext = Depends(get_current_user),
):
    """List document records belonging to one authorized project."""
    documents = database_list_documents(user.tenant_id, project_id)
    if user.project_roles.get(project_id) is None and not user.is_org_admin:
        documents = [document for document in documents if document.get("uploaded_by") == user.user_id]
        if not documents:
            raise HTTPException(status_code=403, detail="You do not have access to this project")
    return [
        document for document in documents
        if can_view_document(
            user,
            project_id=project_id,
            sensitivity_level=document["sensitivity_level"],
            visible_to_teams=json.loads(document.get("visible_to_teams") or "[]"),
            workflow_state=document.get("workflow_state", "draft"),
            uploaded_by=document.get("uploaded_by"),
        )
    ]


@app.get("/documents", response_model=list[DocumentDetailSummary])
def list_all_documents(
    user: UserContext = Depends(get_current_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """List all document records across all projects in the database."""
    _backfill_database_from_vectors(client, user.tenant_id)
    return [
        document for document in database_list_all_documents(user.tenant_id)
        if can_view_document(
            user,
            project_id=document["project_id"],
            sensitivity_level=document["sensitivity_level"],
            visible_to_teams=json.loads(document.get("visible_to_teams") or "[]"),
            workflow_state=document.get("workflow_state", "draft"),
            uploaded_by=document.get("uploaded_by"),
        )
    ]


@app.get("/documents/{document_id}/open", include_in_schema=False)
def open_document(
    document_id: str,
    user: UserContext = Depends(get_current_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """Stream an authorized uploaded document for browser viewing."""
    document = get_document(user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_view_document(
        user,
        project_id=document["project_id"],
        sensitivity_level=document["sensitivity_level"],
        visible_to_teams=json.loads(document.get("visible_to_teams") or "[]"),
        workflow_state=document.get("workflow_state", "draft"),
        uploaded_by=document.get("uploaded_by"),
    ):
        raise HTTPException(status_code=403, detail="You do not have access to this document")
    stored_path = document.get("stored_path")
    project_root = Path(__file__).resolve().parents[2]
    upload_root = (project_root / settings.uploads_path).resolve()
    if stored_path:
        file_path = Path(stored_path)
        if not file_path.is_absolute():
            file_path = project_root / file_path
        file_path = file_path.resolve()
        if upload_root in file_path.parents and file_path.is_file():
            return FileResponse(
                file_path,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f'inline; filename="{Path(document["filename"]).name}"'},
            )

    # Older vector-backfilled records have no local file; expose their indexed text.
    collection = f"tenant_{user.tenant_id}"
    if client.collection_exists(collection):
        points, _ = client.scroll(
            collection_name=collection,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]),
            limit=1000,
            with_payload=True,
        )
        chunks = sorted(
            (point.payload or {} for point in points),
            key=lambda payload: payload.get("chunk_index", 0),
        )
        text = "\n\n".join(payload.get("chunk_text", "") for payload in chunks if payload.get("chunk_text"))
        if text:
            return PlainTextResponse(
                text,
                headers={"Content-Disposition": f'inline; filename="{Path(document["filename"]).stem}.txt"'},
            )
    raise HTTPException(status_code=404, detail="Original file or indexed text is not available")


@app.get("/database/documents/{document_id}")
def get_sqlite_document_record(document_id: str, user: UserContext = Depends(get_current_user)):
    """Return the authorized document metadata stored in SQLite."""
    document = get_document(user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not can_view_document(
        user,
        project_id=document["project_id"],
        sensitivity_level=document["sensitivity_level"],
        visible_to_teams=json.loads(document.get("visible_to_teams") or "[]"),
        workflow_state=document.get("workflow_state", "draft"),
        uploaded_by=document.get("uploaded_by"),
    ):
        raise HTTPException(status_code=403, detail="You do not have access to this document")
    document["visible_to_teams"] = json.loads(document.get("visible_to_teams") or "[]")
    return document


class BatchUploadResponse(BaseModel):
    project_id: str
    documents: list[UploadResponse]
    total_chunks: int


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must contain text")
        return value.strip()


class AskResponse(BaseModel):
    answer: str
    sources: list[SearchResult]


@app.get("/notes")
def get_personal_notes(user: UserContext = Depends(get_current_user)):
    """List only notes owned by the current user in this tenant."""
    return list_notes(user.tenant_id, user.user_id)


@app.post("/notes", status_code=201)
def create_personal_note(request: NoteRequest, user: UserContext = Depends(get_current_user)):
    """Create a personal todo or meeting note, optionally attached to a project."""
    if request.project_id:
        try:
            require_action(user, request.project_id, "view")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    note = create_note(user.tenant_id, user.user_id, request.title.strip(), request.content.strip(), request.project_id)
    audit_log(user.tenant_id, user.user_id, "CREATE_NOTE", "note", note["note_id"], f"project={request.project_id or 'personal'}")
    return note


@app.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    project_name: str = Form(...),
    stage: str = Form(...),
    doc_type: str = Form(...),
    visible_to_teams: str = Form(""),
    sensitivity_level: int = Form(1),
    user: UserContext = Depends(get_current_user),
):
    """Store one document and index its access-tagged chunks.
    
    Requires: user must have reviewer or admin role in the project.
    """
    try:
        require_action(user, project_id, "upload")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    
    return await _ingest_document(
        file, project_id, project_name, stage, doc_type, visible_to_teams, sensitivity_level, user
    )


@app.post("/upload/batch", response_model=BatchUploadResponse, status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(...),
    project_id: str = Form(...),
    project_name: str = Form(...),
    stage: str = Form(...),
    doc_type: str = Form(...),
    visible_to_teams: str = Form(""),
    sensitivity_level: int = Form(1),
    user: UserContext = Depends(get_current_user),
):
    """Upload and index multiple documents into one project knowledge space."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    if len(files) > 100:
        raise HTTPException(status_code=413, detail="Upload at most 100 files at once")

    try:
        require_action(user, project_id, "upload")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    documents = []
    for file in files:
        documents.append(
            await _ingest_document(
                file, project_id, project_name, stage, doc_type, visible_to_teams, sensitivity_level, user
            )
        )
    return BatchUploadResponse(
        project_id=project_id,
        documents=documents,
        total_chunks=sum(document.chunk_count for document in documents),
    )


async def _ingest_document(
    file: UploadFile,
    project_id: str,
    project_name: str,
    stage: str,
    doc_type: str,
    visible_to_teams: str,
    sensitivity_level: int,
    user: UserContext,
) -> UploadResponse:
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    try:
        text = extract_text(contents, file.filename or "")
    except (UnicodeDecodeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    if not text:
        raise HTTPException(status_code=400, detail="No readable text found in the uploaded file")

    # Smart duplicate detection: check if this file already exists
    safe_filename = Path(file.filename or "document").name
    existing_docs = database_list_documents(user.tenant_id, project_id)
    for existing_doc in existing_docs:
        if existing_doc.get("filename") == safe_filename:
            # Same filename found - could be updated version
            audit_log(user.tenant_id, user.user_id, "DUPLICATE_DETECTED", "document", existing_doc.get("document_id"), f"new_upload_for={safe_filename}")
            # Flag for user review but continue (they can keep both or replace)

    document_id = str(uuid4())
    document_dir = UPLOADS_DIR / user.tenant_id
    document_dir.mkdir(parents=True, exist_ok=True)
    stored_file = document_dir / f"{document_id}_{safe_filename}"
    stored_file.write_bytes(contents)

    teams = [team.strip() for team in visible_to_teams.split(",") if team.strip()]
    chunks = chunk_document(
        sections=[ParsedSection(title=safe_filename, text=text)],
        document_id=document_id,
        project_id=project_id,
        project_name=project_name,
        stage=stage,
        doc_type=doc_type,
        visible_to_teams=teams,
        sensitivity_level=sensitivity_level,
    )
    try:
        index_chunks(get_qdrant_client(), user.tenant_id, chunks)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    record_document(
        tenant_id=user.tenant_id,
        project_id=project_id,
        project_name=project_name,
        document_id=document_id,
        filename=safe_filename,
        stored_path=str(stored_file),
        stage=stage,
        doc_type=doc_type,
        sensitivity_level=sensitivity_level,
        chunk_count=len(chunks),
        visible_to_teams=teams,
        uploaded_by=user.user_id,
    )
    
    # Log the upload action
    audit_log(user.tenant_id, user.user_id, "UPLOAD", "document", document_id, f"stage={stage};doc_type={doc_type};sensitivity={sensitivity_level}")

    return UploadResponse(
        document_id=document_id,
        filename=safe_filename,
        stored_path=str(stored_file),
        chunk_count=len(chunks),
    )


# ============= APPROVAL WORKFLOW & ADMIN ENDPOINTS =============

class ApprovalRequest(BaseModel):
    approval_reason: str | None = None


class RejectionRequest(BaseModel):
    rejection_reason: str = Field(min_length=5, max_length=500)


class SetRoleRequest(BaseModel):
    role: str = Field(pattern="^(member|reviewer|admin)$")


class AuditLogEntry(BaseModel):
    log_id: str
    user_id: str
    action: str
    resource_type: str
    resource_id: str | None
    details: str | None
    timestamp: str


class PendingApprovals(BaseModel):
    document_id: str
    filename: str
    stage: str
    doc_type: str
    created_at: str
    created_by: str


class AccessAssignmentRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    project_id: str | None = None
    role: str | None = Field(default=None, pattern="^(member|reviewer|admin)$")
    team_name: str | None = Field(default=None, min_length=1, max_length=120)
    sensitivity_clearance: int | None = Field(default=None, ge=0, le=3)
    organization_admin: bool | None = None


class ProjectAccessRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    project_id: str = Field(min_length=1, max_length=80)
    role: str = Field(pattern="^(member|reviewer|admin)$")


@app.get("/admin/users")
def list_admin_users(user: UserContext = Depends(get_current_user)):
    """List tenant users for organization-admin role management."""
    if not user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only admins can manage roles")
    return list_users(user.tenant_id)


@app.post("/admin/access")
def assign_user_access(
    request: AccessAssignmentRequest,
    admin_user: UserContext = Depends(get_current_user),
):
    """Grant the Admin role to an existing tenant user by email."""
    if not admin_user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only the super admin can assign admin access")
    if request.role != "admin" or request.project_id or request.team_name is not None or request.sensitivity_clearance is not None:
        raise HTTPException(status_code=422, detail="The super admin access screen can grant only the global Admin role")
    target = get_user_by_username(request.email.strip().lower())
    if not target or target["tenant_id"] != admin_user.tenant_id:
        raise HTTPException(status_code=404, detail="User was not found in your organization")
    update_user_access(
        target["user_id"],
        is_org_admin=True,
    )
    details = f"email={target['username']};role=admin"
    audit_log(admin_user.tenant_id, admin_user.user_id, "ASSIGN_ACCESS", "user", target["user_id"], details)
    return {"status": "updated", "user_id": target["user_id"], "email": target["username"]}


@app.post("/admin/project-access")
def assign_project_access(
    request: ProjectAccessRequest,
    admin_user: UserContext = Depends(get_current_user),
):
    """Assign a user to a tenant project by email."""
    if not admin_user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only organization admins can assign project access")
    target = get_user_by_username(request.email.strip().lower())
    if not target or target["tenant_id"] != admin_user.tenant_id:
        raise HTTPException(status_code=404, detail="User was not found in your organization")
    if not get_project(admin_user.tenant_id, request.project_id):
        raise HTTPException(status_code=404, detail="Project was not found in your organization")
    set_user_role(target["user_id"], request.project_id, request.role)
    audit_log(
        admin_user.tenant_id,
        admin_user.user_id,
        "ASSIGN_PROJECT_ACCESS",
        "user",
        target["user_id"],
        f"email={target['username']};project={request.project_id};role={request.role}",
    )
    return {"status": "updated", "email": target["username"], "project_id": request.project_id, "role": request.role}


@app.post("/documents/{document_id}/submit")
def submit_document_endpoint(
    document_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Submit a draft for review."""
    document = get_document(user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        require_document_action(user, document, "submit")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if document.get("workflow_state") not in ("draft", "rejected"):
        raise HTTPException(status_code=409, detail="Only drafts can be submitted")
    submit_document(document_id)
    update_document_workflow_state(get_qdrant_client(), user.tenant_id, document_id, "pending_review")
    audit_log(user.tenant_id, user.user_id, "SUBMIT", "document", document_id)
    return {"status": "pending_review", "document_id": document_id}


@app.post("/documents/{document_id}/approve")
def approve_document_endpoint(
    document_id: str,
    request: ApprovalRequest,
    user: UserContext = Depends(get_current_user),
):
    """Approve a pending document (reviewer/admin only)."""
    document = get_document(user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        require_document_action(user, document, "approve")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        approve_document(document_id, user.user_id)
        update_document_workflow_state(get_qdrant_client(), user.tenant_id, document_id, "approved")
        audit_log(user.tenant_id, user.user_id, "APPROVE", "document", document_id, request.approval_reason)
        return {"status": "approved", "document_id": document_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/documents/{document_id}/reject")
def reject_document_endpoint(
    document_id: str,
    request: RejectionRequest,
    user: UserContext = Depends(get_current_user),
):
    """Reject a document (reviewer/admin only)."""
    document = get_document(user.tenant_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        require_document_action(user, document, "reject")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        reject_document(document_id, request.rejection_reason)
        update_document_workflow_state(get_qdrant_client(), user.tenant_id, document_id, "rejected")
        audit_log(user.tenant_id, user.user_id, "REJECT", "document", document_id, request.rejection_reason)
        return {"status": "rejected", "document_id": document_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/{project_id}/pending-approvals", response_model=list[DocumentSummary])
def get_pending_approvals(
    project_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Get documents awaiting approval in a project (admin only)."""
    try:
        require_action(user, project_id, "pending")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    documents = database_list_documents(user.tenant_id, project_id)
    pending = [
        d for d in documents
        if d.get("workflow_state") == "pending_review"
        and can_view_document(
            user,
            project_id=project_id,
            sensitivity_level=d["sensitivity_level"],
            workflow_state=d["workflow_state"],
        )
    ]
    return pending


@app.post("/admin/users/{user_id}/role")
def set_user_project_role(
    user_id: str,
    project_id: str,
    request: SetRoleRequest,
    admin_user: UserContext = Depends(get_current_user),
):
    """Assign a user's role in a project (admin only)."""
    target = get_user_by_id(user_id)
    project = get_project(admin_user.tenant_id, project_id)
    if not target or target["tenant_id"] != admin_user.tenant_id or not project:
        raise HTTPException(status_code=404, detail="User or project not found in your organization")
    try:
        require_action(admin_user, project_id, "manage_roles")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        set_user_role(user_id, project_id, request.role)
        audit_log(admin_user.tenant_id, admin_user.user_id, "SET_ROLE", "user", user_id, f"role={request.role};project={project_id}")
        return {"status": "updated", "user_id": user_id, "project_id": project_id, "role": request.role}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin/audit-log", response_model=list[AuditLogEntry])
def get_audit_log_endpoint(
    limit: int = 100,
    user: UserContext = Depends(get_current_user),
):
    """Retrieve audit log for the tenant (admin only)."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view audit logs")
    try:
        entries = get_audit_log(user.tenant_id, limit=min(limit, 1000))
        return entries
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class AbacSimulateRequest(BaseModel):
    project_id: str
    sensitivity_level: int = 1
    visible_to_teams: list[str] = Field(default_factory=list)
    stage: str | None = None
    doc_type: str | None = None
    workflow_state: str = "approved"
    uploaded_by: str | None = None


@app.get("/rbac/matrix")
def get_rbac_matrix(user: UserContext = Depends(get_current_user)):
    """Return the complete RBAC role-action hierarchy and current user's role mapping."""
    roles_def = [
        {
            "role": "super_admin",
            "name": "Super Admin / Org Admin",
            "scope": "Tenant-Wide (All Projects)",
            "description": "Full administrative control over tenant settings, user directory, project assignments, and cross-project governance.",
            "actions": ["view", "upload", "draft", "submit", "approve", "reject", "pending", "manage_roles", "audit"],
            "badge_color": "gold",
        },
        {
            "role": "admin",
            "name": "Project Admin",
            "scope": "Assigned Project(s)",
            "description": "Administrative authority within assigned projects, including managing project members and reviewing workflows.",
            "actions": ["view", "upload", "draft", "submit", "approve", "reject", "pending", "manage_roles"],
            "badge_color": "navy",
        },
        {
            "role": "reviewer",
            "name": "Reviewer",
            "scope": "Assigned Project(s)",
            "description": "Authorized to inspect project documentation, review pending submissions, and approve or reject document changes.",
            "actions": ["view", "upload", "draft", "submit", "approve", "reject", "pending"],
            "badge_color": "teal",
        },
        {
            "role": "member",
            "name": "Team Member",
            "scope": "Assigned Project(s)",
            "description": "Standard project member access. Can view authorized documents, ingest/upload new files, and submit drafts for review.",
            "actions": ["view", "upload", "draft", "submit"],
            "badge_color": "slate",
        },
    ]
    all_actions = [
        {"action": "view", "label": "View Documents", "description": "Read authorized project files and search chunks"},
        {"action": "upload", "label": "Upload & Ingest", "description": "Ingest and vectorize new documents into project"},
        {"action": "draft", "label": "Create Drafts", "description": "Save unapproved or draft documents and notes"},
        {"action": "submit", "label": "Submit for Review", "description": "Send draft document to Reviewer queue"},
        {"action": "approve", "label": "Approve Submissions", "description": "Publish reviewed document for project-wide access"},
        {"action": "reject", "label": "Reject Submissions", "description": "Return document with required rejection rationale"},
        {"action": "pending", "label": "Inspect Review Queue", "description": "Access pending-review documents queue"},
        {"action": "manage_roles", "label": "Manage Project Roles", "description": "Assign Member, Reviewer, Admin roles to users"},
        {"action": "audit", "label": "Audit Logs", "description": "Inspect tenant-wide security and access audit trail"},
    ]
    return {
        "roles": roles_def,
        "actions": all_actions,
        "user_role": user.role,
        "is_org_admin": user.is_org_admin,
        "project_roles": user.project_roles,
    }


@app.post("/abac/simulate")
def simulate_abac_policy(
    request: AbacSimulateRequest,
    user: UserContext = Depends(get_current_user),
):
    """Simulate and evaluate multi-attribute access control policies against document attributes."""
    user_db = get_user_by_id(user.user_id) if user.user_id else None
    user_team = user_db.get("team_name") if user_db else (user.team_memberships.get(request.project_id, [None])[0] if user.team_memberships else None)

    evaluations = []

    # 1. Tenant Isolation check
    evaluations.append({
        "rule_name": "Tenant Collection Isolation",
        "dimension": "Tenant Boundary",
        "required": f"Tenant '{user.tenant_id}'",
        "actual": f"Tenant '{user.tenant_id}'",
        "passed": True,
        "explanation": f"Request is isolated within tenant collection '{user.tenant_id}'. Cross-tenant access is physically blocked at database vector layer.",
    })

    # 2. Project Scope check
    is_project_accessible = user.is_org_admin or (request.project_id in user.project_roles)
    user_proj_role = "org_admin" if user.is_org_admin else user.project_roles.get(request.project_id)
    evaluations.append({
        "rule_name": "Project Scope Membership",
        "dimension": "Project Scope",
        "required": f"Role assigned in project '{request.project_id}'",
        "actual": f"Role '{user_proj_role}'" if user_proj_role else "No project assignment",
        "passed": is_project_accessible,
        "explanation": "Super admin bypasses project restrictions with tenant-wide clearance" if user.is_org_admin else (
            f"User has '{user_proj_role}' role in project '{request.project_id}'." if is_project_accessible else
            f"User has not been granted membership in project '{request.project_id}'."
        ),
    })

    # 3. Sensitivity Level vs Clearance
    clearance_passed = user.is_org_admin or (user.sensitivity_clearance >= request.sensitivity_level)
    level_names = {0: "0 (Public)", 1: "1 (Internal)", 2: "2 (Confidential)", 3: "3 (Restricted)"}
    evaluations.append({
        "rule_name": "Sensitivity Clearance Enforcement",
        "dimension": "Sensitivity Clearance",
        "required": f"Clearance >= Level {level_names.get(request.sensitivity_level, str(request.sensitivity_level))}",
        "actual": f"User Clearance Level {level_names.get(user.sensitivity_clearance, str(user.sensitivity_clearance))}" if not user.is_org_admin else "Super Admin (Level 3 Bypass)",
        "passed": clearance_passed,
        "explanation": "Clearance is sufficient to read document content." if clearance_passed else f"User clearance (Level {user.sensitivity_clearance}) is lower than document sensitivity (Level {request.sensitivity_level}). Access prohibited.",
    })

    # 4. Team Visibility Tagging
    teams_req = request.visible_to_teams or []
    team_passed = (len(teams_req) == 0) or user.is_org_admin or (bool(user_team) and user_team in teams_req)
    evaluations.append({
        "rule_name": "Team Visibility Partition",
        "dimension": "Team Membership Tag",
        "required": f"Visible to: [{', '.join(teams_req)}]" if teams_req else "Unrestricted (All Teams in Project)",
        "actual": f"User Team: '{user_team}'" if user_team else "No team assigned",
        "passed": team_passed,
        "explanation": "Document is open to all teams within the project." if not teams_req else (
            "User's team tag matches document visibility tag." if team_passed else f"Document is restricted to [{', '.join(teams_req)}], whereas user belongs to '{user_team}'."
        ),
    })

    # 5. Lifecycle & Workflow State
    can_review = user.is_org_admin or user_proj_role in ("admin", "reviewer")
    is_owner = bool(request.uploaded_by) and request.uploaded_by == user.user_id
    workflow_passed = (request.workflow_state == "approved") or is_owner or can_review
    evaluations.append({
        "rule_name": "Document Lifecycle & State",
        "dimension": "Workflow State Attribute",
        "required": "State == 'approved' OR uploaded_by == user OR Reviewer/Admin role",
        "actual": f"State: '{request.workflow_state}' | Owner: {is_owner} | Reviewer: {can_review}",
        "passed": workflow_passed,
        "explanation": "Document is approved for general access." if request.workflow_state == "approved" else (
            "User is the original uploader (draft/pending owner access)." if is_owner else (
                "User has Reviewer/Admin role to inspect unapproved submissions." if can_review else
                f"Document is in '{request.workflow_state}' state and cannot be viewed by regular members until approved."
            )
        ),
    })

    overall_allowed = is_project_accessible and clearance_passed and team_passed and workflow_passed

    q_filter = {}
    try:
        raw_filter = build_access_filter(user, request.project_id if is_project_accessible else None)
        q_filter = {
            "must": [
                cond.model_dump() if hasattr(cond, "model_dump") else (
                    cond.dict() if hasattr(cond, "dict") else str(cond)
                )
                for cond in (raw_filter.must or [])
            ]
        }
    except Exception as exc:
        q_filter = {"filter_error": str(exc)}

    return {
        "allowed": overall_allowed,
        "verdict": "ACCESS GRANTED (ALLOW)" if overall_allowed else "ACCESS DENIED (DENY)",
        "user_context": {
            "user_id": user.user_id,
            "tenant_id": user.tenant_id,
            "is_org_admin": user.is_org_admin,
            "role": user.role,
            "team_name": user_team,
            "sensitivity_clearance": user.sensitivity_clearance,
        },
        "evaluations": evaluations,
        "qdrant_filter": q_filter,
    }


@app.get("/stages", response_model=list[str])
def get_available_stages(user: UserContext = Depends(get_optional_user)):
    """Get valid SDLC stages for the tenant."""
    return get_valid_stages(user.tenant_id)


@app.post("/ask", response_model=AskResponse)
def ask_documents(
    request: AskRequest,
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """Retrieve authorized chunks and answer the question with Gemini."""
    start = time.time()
    try:
        access_filter = build_access_filter(user, project_id=request.project_id)
        hits = hybrid_search(
            client=client,
            tenant_id=user.tenant_id,
            query_text=request.query,
            dense_vector=embed_dense(request.query, task_type="RETRIEVAL_QUERY"),
            sparse_vector=embed_sparse(request.query),
            access_filter=access_filter,
        )
        if not hits:
            no_projects = not user.is_org_admin and not user.project_roles
            if no_projects:
                return AskResponse(
                    answer=(
                        "You haven't uploaded any project documents yet.\n\n"
                        "To get started:\n"
                        "1. Go to **04 Ingest Documents** in the sidebar\n"
                        "2. Create a project and upload your first document (PDF, Word, Markdown, etc.)\n"
                        "3. Come back here and ask any question about your documents!\n\n"
                        "DocFlow will use Gemini AI to answer questions grounded in your uploaded content."
                    ),
                    sources=[]
                )
            return AskResponse(answer="I could not find relevant information in the uploaded documents.", sources=[])
        context = "\n\n".join(
            f"[Source {index + 1}: {hit['payload']['document_id']}, {hit['payload']['section_title']}]\n"
            f"{hit['payload']['chunk_text']}"
            for index, hit in enumerate(hits)
        )
        answer = generate_answer(
            "Answer the question using only the context below. Cite sources as [Source N]. "
            "If the context does not contain the answer, say so clearly.\n\n"
            f"Question: {request.query}\n\nContext:\n{context}"
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sources = [
        SearchResult(
            document_id=hit["payload"]["document_id"],
            section_title=hit["payload"]["section_title"],
            chunk_text=hit["payload"]["chunk_text"],
            score=hit["score"],
        )
        for hit in hits
    ]
    
    # Telemetry
    latency_ms = (time.time() - start) * 1000
    PerformanceMetrics.log_query_latency(request.query, latency_ms, len(hits))
    
    return AskResponse(answer=answer, sources=sources)


@app.post("/search", response_model=list[SearchResult])
def search_documents(
    request: SearchRequest,
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """Search documents with hybrid retrieval and return matching chunks."""
    start = time.time()
    
    try:
        access_filter = build_access_filter(user, project_id=request.project_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        dense_vector = embed_dense(request.query, task_type="RETRIEVAL_QUERY")
        sparse_vector = embed_sparse(request.query)
        hits = hybrid_search(
            client=client,
            tenant_id=user.tenant_id,
            query_text=request.query,
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            access_filter=access_filter,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    results = [
        SearchResult(
            document_id=hit["payload"]["document_id"],
            section_title=hit["payload"]["section_title"],
            chunk_text=hit["payload"]["chunk_text"],
            score=hit["score"],
        )
        for hit in hits
    ]
    
    # Telemetry
    latency_ms = (time.time() - start) * 1000
    PerformanceMetrics.log_query_latency(request.query, latency_ms, len(results))
    
    return results


# ============= AGENT ENDPOINTS =============

from app.agents import DraftingAgent, GapDetectionAgent, GeneralQueryAgent


class GenerateOutlineRequest(BaseModel):
    project_id: str
    stage: str


class GenerateOutlineResponse(BaseModel):
    outline: str
    stage: str


class GapAnalysisResponse(BaseModel):
    project_id: str
    total_gaps: int
    gaps_by_stage: dict
    gap_report: str


class SuggestContentRequest(BaseModel):
    document_type: str
    project_context: str
    stage: str


class FollowupSuggestions(BaseModel):
    followup_questions: list[str]


@app.post("/agents/drafting/outline", response_model=GenerateOutlineResponse)
def agent_generate_outline(
    request: GenerateOutlineRequest,
    user: UserContext = Depends(get_current_user),
):
    """Generate a documentation outline for a project stage (Drafting Agent)."""
    try:
        documents = database_list_documents(user.tenant_id, request.project_id)
        outline = DraftingAgent.generate_document_outline(
            project_id=request.project_id,
            stage=request.stage,
            existing_docs=documents,
            user=user,
        )
        audit_log(user.tenant_id, user.user_id, "AGENT_CALL", "drafting_agent", request.project_id, f"stage={request.stage}")
        return GenerateOutlineResponse(outline=outline, stage=request.stage)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/agents/gap-detection/analyze", response_model=GapAnalysisResponse)
def agent_analyze_gaps(
    project_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Analyze documentation gaps in a project (Gap-Detection Agent)."""
    try:
        stages = get_valid_stages(user.tenant_id)
        documents = database_list_documents(user.tenant_id, project_id)
        
        gaps = GapDetectionAgent.detect_gaps(
            project_id=project_id,
            stages=stages,
            existing_docs=documents,
        )
        
        gap_report = GapDetectionAgent.generate_gap_report(
            project_id=project_id,
            gaps=gaps,
            existing_docs=documents,
        )
        
        audit_log(user.tenant_id, user.user_id, "AGENT_CALL", "gap_detection_agent", project_id, f"gaps_found={gaps['total_gaps']}")
        
        return GapAnalysisResponse(
            project_id=project_id,
            total_gaps=gaps["total_gaps"],
            gaps_by_stage=gaps["gaps_by_stage"],
            gap_report=gap_report,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/agents/query/followups", response_model=FollowupSuggestions)
def agent_suggest_followups(
    request: AskRequest,
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """Suggest follow-up questions based on an answer (General Query Agent)."""
    try:
        access_filter = build_access_filter(user, project_id=request.project_id)
        hits = hybrid_search(
            client=client,
            tenant_id=user.tenant_id,
            query_text=request.query,
            dense_vector=embed_dense(request.query, task_type="RETRIEVAL_QUERY"),
            sparse_vector=embed_sparse(request.query),
            access_filter=access_filter,
        )
        
        if not hits:
            return FollowupSuggestions(followup_questions=[])
        
        # Generate initial answer
        context = "\n\n".join(
            f"[Source {index + 1}: {hit['payload']['document_id']}]\n{hit['payload']['chunk_text']}"
            for index, hit in enumerate(hits[:3])
        )
        answer = generate_answer(f"Briefly answer: {request.query}\n\nContext:\n{context}")
        
        # Suggest follow-ups
        followups = GeneralQueryAgent.suggest_followup_queries(request.query, answer)
        
        audit_log(user.tenant_id, user.user_id, "AGENT_CALL", "query_agent", request.project_id or "all", f"followups={len(followups)}")
        
        return FollowupSuggestions(followup_questions=followups)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
