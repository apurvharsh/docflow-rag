from fastapi.testclient import TestClient

from app.api import search
from app.auth import user_from_token
from app.database import get_user_by_username


def test_login_returns_token_and_token_resolves_user(monkeypatch):
    monkeypatch.setattr(search.settings, "auth_secret", "test-secret")
    monkeypatch.setattr(search.settings, "auth_username", "alice@example.com")
    monkeypatch.setattr(search.settings, "auth_password", "correct-password")
    response = TestClient(search.app).post(
        "/login",
        json={"email": "alice@example.com", "password": "correct-password"},
    )

    assert response.status_code == 200
    assert user_from_token(response.json()["access_token"]).user_id == search.settings.dev_user_id


def test_protected_context_requires_authentication():
    response = TestClient(search.app).get("/me")
    assert response.status_code == 401


def test_signup_creates_account_and_allows_login(monkeypatch, tmp_path):
    monkeypatch.setattr(search.settings, "database_path", str(tmp_path / "accounts.db"))
    monkeypatch.setattr(search.settings, "auth_secret", "test-secret")
    search.initialize_database()
    client = TestClient(search.app)

    signup = client.post("/signup", json={"email": "new.user@example.com", "password": "correct-password", "full_name": "New User", "organization": "Acme Delivery", "team_name": "Platform Engineering", "job_title": "Engineer"})
    login = client.post("/login", json={"email": "new.user@example.com", "password": "correct-password"})

    assert signup.status_code == 201
    assert signup.json().get("is_new_user") is True
    assert login.status_code == 200
    assert login.json().get("is_new_user") is False
    assert user_from_token(login.json()["access_token"]).user_id
    profile = get_user_by_username("new.user@example.com")
    assert profile["team_name"] == "Platform Engineering"
    assert profile["job_title"] == "Engineer"


def test_signup_rejects_duplicate_account(monkeypatch, tmp_path):
    monkeypatch.setattr(search.settings, "database_path", str(tmp_path / "accounts.db"))
    monkeypatch.setattr(search.settings, "auth_secret", "test-secret")
    search.initialize_database()
    client = TestClient(search.app)
    payload = {"email": "new.user@example.com", "password": "correct-password", "full_name": "New User", "organization": "Acme Delivery", "team_name": "Platform Engineering", "job_title": "Engineer"}

    assert client.post("/signup", json=payload).status_code == 201
    assert client.post("/signup", json=payload).status_code == 409


def test_google_state_cookie_is_sent_over_local_http(monkeypatch):
    monkeypatch.setattr(search.settings, "google_client_id", "client-id")
    monkeypatch.setattr(search.settings, "google_client_secret", "client-secret")
    monkeypatch.setattr(search, "google_authorization_url", lambda state: f"https://accounts.google.com/?state={state}")
    client = TestClient(search.app)

    start = client.get("/auth/google/start", follow_redirects=False)
    state = start.cookies.get("google_oauth_state")

    assert start.status_code == 307
    assert state
    assert "Secure" not in start.headers["set-cookie"]


def test_protected_projects_documents_and_ask_require_authentication(monkeypatch):
    client = TestClient(search.app)
    assert client.get("/projects").status_code == 401
    assert client.get("/documents").status_code == 401
    assert client.post("/ask", json={"query": "What is the project scope?"}).status_code == 401


def test_demo_login_creates_account_and_returns_valid_token(monkeypatch, tmp_path):
    monkeypatch.setattr(search.settings, "database_path", str(tmp_path / "demo_accounts.db"))
    monkeypatch.setattr(search.settings, "auth_secret", "test-secret")
    search.initialize_database()
    client = TestClient(search.app)

    response = client.post("/auth/demo")
    assert response.status_code == 200
    token = response.json()["access_token"]
    user_context = user_from_token(token)
    assert user_context.user_id
    assert user_context.is_org_admin is True
    assert user_context.sensitivity_clearance == 1


def test_authorized_document_open_supports_existing_file_and_indexed_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(search.settings, "database_path", str(tmp_path / "open.db"))
    monkeypatch.setattr(search.settings, "auth_secret", "test-secret")
    monkeypatch.setattr(search.settings, "uploads_path", str(tmp_path / "uploads"))
    search.initialize_database()
    client = TestClient(search.app)
    token = client.post("/auth/demo").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    upload_root = tmp_path / "uploads" / "local"
    upload_root.mkdir(parents=True)
    stored_file = upload_root / "doc-1_notes.txt"
    stored_file.write_text("Original notes", encoding="utf-8")
    from app.database import record_document
    record_document(
        tenant_id="local", project_id="project-a", project_name="Project A", document_id="doc-1",
        filename="notes.txt", stored_path=str(stored_file), stage="Design", doc_type="Notes",
        sensitivity_level=1, chunk_count=1, uploaded_by="local-user",
    )
    monkeypatch.setitem(search.app.dependency_overrides, search.get_qdrant_client, lambda: object())
    original = client.get("/documents/doc-1/open", headers=headers)
    assert original.status_code == 200
    assert original.content == b"Original notes"
