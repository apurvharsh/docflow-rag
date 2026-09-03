import pytest

from app.models.schema import SensitivityLevel, UserContext
from app.retrieval.access_filter import build_access_filter
from qdrant_client import models


def make_user(**overrides) -> UserContext:
    defaults = dict(
        user_id="u1",
        tenant_id="t1",
        is_org_admin=False,
        project_roles={"proj_a": "member"},
        team_memberships={"proj_a": ["team_eng"]},
        sensitivity_clearance=SensitivityLevel.INTERNAL,
    )
    defaults.update(overrides)
    return UserContext(**defaults)


def test_member_filter_is_scoped_to_memberships_and_attributes():
    user = make_user()
    result = build_access_filter(user)
    assert len(result.must) == 1
    assert isinstance(result.must[0], models.Filter)
    assert result.must[0].should[0].key == "project_id"


def test_org_admin_uses_tenant_collection_as_boundary():
    """Admins can access all attributes inside their tenant collection."""
    admin = make_user(is_org_admin=True, project_roles={}, team_memberships={})
    result = build_access_filter(admin, project_id=None)
    # Admins get empty filter = no restrictions
    assert result.must == []


def test_admin_project_scope_remains_inside_tenant_collection():
    admin = make_user(is_org_admin=True, project_roles={}, team_memberships={})
    result = build_access_filter(admin, project_id="proj_a")
    # Admins still get empty filter
    assert result.must == []


def test_admin_filter_is_not_limited_by_document_attributes():
    admin = make_user(
        is_org_admin=True,
        project_roles={},
        team_memberships={},
        sensitivity_clearance=SensitivityLevel.PUBLIC,
    )

    result = build_access_filter(admin)
    # Admins see everything; app layer would enforce other restrictions for non-admins
    assert result.must == []
