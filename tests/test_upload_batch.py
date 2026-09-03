from fastapi.testclient import TestClient

from app.api import search
from app.models.schema import UserContext


def test_batch_upload_accepts_multiple_project_files(monkeypatch):
    user = UserContext(user_id="user-1", tenant_id="tenant-1", is_org_admin=True)
    monkeypatch.setattr(search, "index_chunks", lambda client, tenant_id, chunks: None)
    monkeypatch.setattr(search, "get_qdrant_client", lambda: object())
    search.app.dependency_overrides[search.get_current_user] = lambda: user

    try:
        response = TestClient(search.app).post(
            "/upload/batch",
            data={
                "project_id": "project-1",
                "project_name": "Project One",
                "stage": "Design",
                "doc_type": "Notes",
            },
            files=[
                ("files", ("one.txt", b"first document", "text/plain")),
                ("files", ("two.txt", b"second document", "text/plain")),
            ],
        )
    finally:
        search.app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 201
    assert body["project_id"] == "project-1"
    assert len(body["documents"]) == 2
    assert body["documents"][0]["document_id"] != body["documents"][1]["document_id"]
    assert body["total_chunks"] == 2


def test_upload_allows_project_outside_user_membership(monkeypatch):
    # User is admin so they can upload to any project
    user = UserContext(
        user_id="user-1",
        tenant_id="tenant-1",
        is_org_admin=True,
        project_roles={},
        sensitivity_clearance=1,
    )
    monkeypatch.setattr(search, "index_chunks", lambda client, tenant_id, chunks: None)
    monkeypatch.setattr(search, "get_qdrant_client", lambda: object())
    search.app.dependency_overrides[search.get_current_user] = lambda: user

    try:
        response = TestClient(search.app).post(
            "/upload",
            data={"project_id": "blocked-project", "project_name": "Blocked", "stage": "Design", "doc_type": "Notes"},
            files={"file": ("blocked.txt", b"private", "text/plain")},
        )
    finally:
        search.app.dependency_overrides.clear()

    assert response.status_code == 201


def test_project_listing_backfills_when_other_projects_already_exist(monkeypatch):
    user = UserContext(user_id="user-1", tenant_id="tenant-1", is_org_admin=True)
    initial_projects = [{"project_id": "existing", "project_name": "Existing", "document_count": 1}]
    recovered_projects = initial_projects + [
        {"project_id": "recovered", "project_name": "Recovered", "document_count": 2}
    ]
    calls = []

    def list_projects(tenant_id):
        calls.append(tenant_id)
        return initial_projects if len(calls) == 1 else recovered_projects

    monkeypatch.setattr(search, "database_list_projects", list_projects)
    monkeypatch.setattr(
        search,
        "_backfill_database_from_vectors",
        lambda client, tenant_id: calls.append(("backfill", tenant_id)),
    )

    result = search.list_projects(user=user, client=object())

    assert result == recovered_projects
    assert calls == [("backfill", "tenant-1"), "tenant-1"]