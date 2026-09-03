"""build_access_filter() — ABAC/RBAC filtering for query access control.

Enforces project-scoped RBAC access; tenant isolation comes from the Qdrant
collection selected by the caller.
"""

from typing import Optional
from qdrant_client import models
from app.authorization import role_for_project
from app.models.schema import UserContext, SensitivityLevel


def build_access_filter(
    user: UserContext,
    project_id: Optional[str] = None,
) -> models.Filter:
    """Return a Qdrant filter enforcing ABAC/RBAC policy for the user.
    
        Core rule:
        - Organization admins see all documents inside their tenant collection.
        - Project members see every document for their assigned projects.
    
    The tenant boundary is supplied by the collection name; all other attributes
    are applied here so every retrieval leg receives the same policy.
    """
    
    filters = []
    if user.is_org_admin:
        return models.Filter(must=[])

    if project_id:
        if role_for_project(user, project_id) is None:
            raise PermissionError("You do not have access to this project")
        filters.append(models.FieldCondition(key="project_id", match=models.MatchValue(value=project_id)))
    elif not user.is_org_admin:
        if not user.project_roles:
            # User has no projects yet — return a filter that matches nothing.
            # This allows the endpoint to return an empty-results response
            # gracefully instead of blocking with a 403 error.
            # Any user can create projects and upload documents from scratch.
            filters.append(
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="project_id",
                            match=models.MatchValue(value="__no_projects__")
                        )
                    ]
                )
            )
        else:
            filters.append(
                models.Filter(
                    should=[
                        models.FieldCondition(key="project_id", match=models.MatchValue(value=project))
                        for project in user.project_roles
                    ]
                )
            )

    if filters:
        return models.Filter(must=filters)
    return models.Filter(must=[])
