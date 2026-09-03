"""Project and document listing routes."""

from fastapi import APIRouter, Depends
from qdrant_client import QdrantClient

from app.api.dependencies import get_qdrant_client, get_optional_user
from app.database import list_projects, list_documents, list_all_documents
from app.models.responses import ProjectSummary, DocumentSummary, DocumentDetailSummary
from app.models.schema import UserContext

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectSummary])
def list_user_projects(
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """List projects visible to the current user."""
    _backfill_database_from_vectors(client, user.tenant_id)
    projects = list_projects(user.tenant_id)
    return projects


@router.get("/projects/{project_id}/documents", response_model=list[DocumentSummary])
def list_project_documents(
    project_id: str,
    user: UserContext = Depends(get_optional_user),
):
    """List documents in a specific project."""
    return list_documents(user.tenant_id, project_id)


@router.get("/documents", response_model=list[DocumentDetailSummary])
def list_all_user_documents(
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """List all documents across all projects."""
    _backfill_database_from_vectors(client, user.tenant_id)
    return list_all_documents(user.tenant_id)


def _backfill_database_from_vectors(client: QdrantClient, tenant_id: str) -> None:
    """Register pre-database Qdrant documents so existing data remains visible."""
    from app.database import record_document
    
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
