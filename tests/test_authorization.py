from app.authorization import can_view_document, require_action, require_document_action
from app.models.schema import UserContext


def make_user(**overrides):
    values = {
        "user_id": "u1",
        "tenant_id": "tenant-a",
        "is_org_admin": False,
        "role": "member",
        "project_roles": {"project-a": "member"},
        "team_memberships": {"project-a": ["team-a"]},
        "sensitivity_clearance": 1,
    }
    values.update(overrides)
    return UserContext(**values)


def test_member_can_upload_and_submit_only_in_authorized_project():
    user = make_user()
    assert require_action(user, "project-a", "upload") == "member"
    assert require_action(user, "project-a", "submit") == "member"

    try:
        require_action(user, "project-b", "upload")
    except PermissionError:
        pass
    else:
        raise AssertionError("unauthorized project upload was allowed")


def test_reviewer_can_approve_but_member_cannot():
    document = {
        "tenant_id": "tenant-a",
        "project_id": "project-a",
        "sensitivity_level": 1,
    }
    reviewer = make_user(role="reviewer", project_roles={"project-a": "reviewer"})
    assert require_document_action(reviewer, document, "approve") == "reviewer"

    try:
        require_document_action(make_user(), document, "approve")
    except PermissionError:
        pass
    else:
        raise AssertionError("member approval was allowed")


def test_project_assignment_allows_any_file_and_admin_stays_tenant_bound():
    user = make_user()
    assert can_view_document(
        user,
        project_id="project-a",
        sensitivity_level=1,
        visible_to_teams=["team-a"],
        workflow_state="approved",
    )
    assert can_view_document(
        user,
        project_id="project-a",
        sensitivity_level=2,
        visible_to_teams=["team-a"],
        workflow_state="approved",
    )
    assert can_view_document(
        user,
        project_id="project-a",
        sensitivity_level=1,
        visible_to_teams=["team-b"],
        workflow_state="approved",
    )
    admin = make_user(is_org_admin=True, role="admin", project_roles={})
    assert can_view_document(
        admin,
        project_id="project-a",
        sensitivity_level=3,
        visible_to_teams=["team-b"],
        workflow_state="draft",
    )
    try:
        require_document_action(admin, {"tenant_id": "tenant-b", "project_id": "project-a", "sensitivity_level": 1}, "approve")
    except PermissionError:
        pass
    else:
        raise AssertionError("cross-tenant admin action was allowed")


def test_member_can_see_own_uploaded_draft():
    user = make_user(project_roles={}, team_memberships={})
    assert can_view_document(
        user,
        project_id="new-project",
        sensitivity_level=1,
        workflow_state="draft",
        uploaded_by="u1",
    )


def test_any_project_member_can_open_another_members_document():
    user = make_user()
    assert can_view_document(
        user,
        project_id="project-a",
        sensitivity_level=1,
        visible_to_teams=["team-a"],
        workflow_state="draft",
        uploaded_by="another-user",
    )
