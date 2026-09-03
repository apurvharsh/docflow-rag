"""System and user context routes."""

from pathlib import Path
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.dependencies import get_current_user
from app.models.responses import AccessContext
from app.models.schema import UserContext

router = APIRouter(tags=["system"])
UI_DIR = Path(__file__).parent.parent.parent / "ui"


@router.get("/", include_in_schema=False)
def dashboard():
    """Serve React dashboard UI."""
    return FileResponse(UI_DIR / "index.html")


@router.get("/react-app.js", include_in_schema=False)
def react_app():
    """Serve React application JavaScript."""
    return FileResponse(UI_DIR / "react-app.js", media_type="application/javascript")


@router.get("/health", include_in_schema=False)
def health():
    """Health check endpoint."""
    return {"status": "ok"}


@router.get("/me", response_model=AccessContext)
def current_access_context(user: UserContext = Depends(get_current_user)):
    """Get current user's access context."""
    from app.database import list_projects
    
    projects = list_projects(user.tenant_id)
    project_ids = [p["project_id"] for p in projects]
    
    return AccessContext(
        user_id=user.user_id,
        tenant_id=user.tenant_id,
        is_org_admin=user.is_org_admin,
        sensitivity_clearance=user.sensitivity_clearance,
        accessible_projects=project_ids,
    )
