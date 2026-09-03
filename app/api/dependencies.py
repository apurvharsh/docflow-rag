"""Shared FastAPI dependencies."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from qdrant_client import QdrantClient

from app.config import settings
from app.auth import user_from_token
from app.models.schema import UserContext


bearer = HTTPBearer(auto_error=False)
_qdrant_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Get or create Qdrant client (singleton)."""
    global _qdrant_client
    if _qdrant_client is None:
        if settings.qdrant_url:
            _qdrant_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
        else:
            _qdrant_client = QdrantClient(path=settings.qdrant_path)
    return _qdrant_client


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UserContext:
    """Dependency: Get authenticated user or raise 401."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return user_from_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> UserContext:
    """Dependency: Get user if authenticated, otherwise return demo user."""
    if credentials is not None and credentials.credentials:
        try:
            return user_from_token(credentials.credentials)
        except ValueError:
            pass
    return UserContext(
        user_id=settings.dev_user_id,
        tenant_id=settings.dev_tenant_id,
        is_org_admin=settings.dev_org_admin,
        sensitivity_clearance=settings.dev_sensitivity_clearance,
    )
