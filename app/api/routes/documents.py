"""Document upload and retrieval routes."""

import time
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from qdrant_client import QdrantClient

from app.api.dependencies import get_current_user, get_optional_user, get_qdrant_client
from app.config import settings
from app.database import list_documents as database_list_documents, record_document, audit_log as db_audit_log
from app.authorization import require_action
from app.ingestion.chunking import ParsedSection, chunk_document
from app.ingestion.document_text import extract_text
from app.ingestion.indexing import index_chunks
from app.models.requests import SearchRequest, AskRequest
from app.models.responses import UploadResponse, BatchUploadResponse, SearchResult, AskResponse
from app.models.schema import UserContext
from app.retrieval.access_filter import build_access_filter
from app.retrieval.embeddings import embed_dense, embed_sparse, generate_answer
from app.retrieval.hybrid_search import hybrid_search
from app.telemetry import PerformanceMetrics

router = APIRouter(tags=["documents"])
UPLOADS_DIR = Path(settings.uploads_path)


@router.post("/upload", response_model=UploadResponse, status_code=201)
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
    """Upload a single document."""
    try:
        require_action(user, project_id, "upload")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    
    return await _ingest_document(
        file, project_id, project_name, stage, doc_type, visible_to_teams, sensitivity_level, user
    )


@router.post("/upload/batch", response_model=BatchUploadResponse, status_code=201)
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
    """Upload multiple documents (up to 100)."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")
    if len(files) > 100:
        raise HTTPException(status_code=413, detail="Upload at most 100 files at once")

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


@router.post("/ask", response_model=AskResponse)
def ask_documents(
    request: AskRequest,
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """Ask AI question about project documents."""
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
    
    latency_ms = (time.time() - start) * 1000
    PerformanceMetrics.log_query_latency(request.query, latency_ms, len(hits))
    
    return AskResponse(answer=answer, sources=sources)


@router.post("/search", response_model=list[SearchResult])
def search_documents(
    request: SearchRequest,
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """Search documents with hybrid retrieval."""
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
    
    latency_ms = (time.time() - start) * 1000
    PerformanceMetrics.log_query_latency(request.query, latency_ms, len(results))
    
    return results


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
    """Process and store a document."""
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    try:
        text = extract_text(contents, file.filename or "")
    except (UnicodeDecodeError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    if not text:
        raise HTTPException(status_code=400, detail="No readable text found in the uploaded file")

    # Smart duplicate detection
    safe_filename = Path(file.filename or "document").name
    existing_docs = database_list_documents(user.tenant_id, project_id)
    for existing_doc in existing_docs:
        if existing_doc.get("filename") == safe_filename:
            db_audit_log(user.tenant_id, user.user_id, "DUPLICATE_DETECTED", "document", 
                        existing_doc.get("document_id"), f"new_upload_for={safe_filename}")

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
    )
    
    db_audit_log(user.tenant_id, user.user_id, "UPLOAD", "document", document_id, 
                f"stage={stage};doc_type={doc_type};sensitivity={sensitivity_level}")

    return UploadResponse(
        document_id=document_id,
        filename=safe_filename,
        stored_path=str(stored_file),
        chunk_count=len(chunks),
    )
