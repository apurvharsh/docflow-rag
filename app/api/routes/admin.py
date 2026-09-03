"""Administrative routes for governance and approval workflows."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_user
from app.database import (
    get_user_role, list_documents, approve_document, reject_document,
    audit_log, get_audit_log, set_user_role
)
from app.models.requests import ApprovalRequest, RejectionRequest, SetRoleRequest
from app.models.responses import DocumentSummary, AuditLogEntry
from app.models.schema import UserContext

router = APIRouter(prefix="/admin", tags=["administration"])


@router.post("/documents/{document_id}/approve")
def approve_document_route(
    document_id: str,
    request: ApprovalRequest,
    user: UserContext = Depends(get_current_user),
):
    """Approve a pending document (admin only)."""
    if not user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only admins can approve documents")
    
    try:
        approve_document(document_id, user.user_id)
        audit_log(user.tenant_id, user.user_id, "APPROVE", "document", document_id, request.approval_reason)
        return {"status": "approved", "document_id": document_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/documents/{document_id}/reject")
def reject_document_route(
    document_id: str,
    request: RejectionRequest,
    user: UserContext = Depends(get_current_user),
):
    """Reject a document (admin only)."""
    if not user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only admins can reject documents")
    
    try:
        reject_document(document_id, request.rejection_reason)
        audit_log(user.tenant_id, user.user_id, "REJECT", "document", document_id, request.rejection_reason)
        return {"status": "rejected", "document_id": document_id}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/pending-approvals", response_model=list[DocumentSummary])
def get_pending_approvals_route(
    project_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Get documents awaiting approval in a project (admin only)."""
    if not user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only admins can view pending approvals")
    
    documents = list_documents(user.tenant_id, project_id)
    pending = [d for d in documents if d.get("workflow_state") == "pending_review"]
    return pending


@router.post("/users/{user_id}/role")
def set_user_project_role_route(
    user_id: str,
    project_id: str,
    request: SetRoleRequest,
    admin_user: UserContext = Depends(get_current_user),
):
    """Assign a user's role in a project (admin only)."""
    if not admin_user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only admins can assign roles")
    
    try:
        set_user_role(user_id, project_id, request.role)
        audit_log(admin_user.tenant_id, admin_user.user_id, "SET_ROLE", "user", user_id, 
                 f"role={request.role};project={project_id}")
        return {"status": "updated", "user_id": user_id, "project_id": project_id, "role": request.role}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit-log", response_model=list[AuditLogEntry])
def get_audit_log_route(
    limit: int = 100,
    user: UserContext = Depends(get_current_user),
):
    """Retrieve audit log for the tenant (admin only)."""
    if not user.is_org_admin:
        raise HTTPException(status_code=403, detail="Only admins can view audit logs")
    
    try:
        entries = get_audit_log(user.tenant_id, limit=min(limit, 1000))
        return entries
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
