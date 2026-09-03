"""SQLite application database for projects and uploaded documents."""

import json
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone
from app.config import settings


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                project_name TEXT NOT NULL,
                owner_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, project_id)
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT,
                provider TEXT NOT NULL,
                provider_subject TEXT UNIQUE,
                tenant_id TEXT NOT NULL,
                is_org_admin INTEGER NOT NULL DEFAULT 0,
                sensitivity_clearance INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                stage TEXT NOT NULL,
                doc_type TEXT NOT NULL,
                sensitivity_level INTEGER NOT NULL,
                visible_to_teams TEXT NOT NULL DEFAULT '[]',
                uploaded_by TEXT,
                chunk_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id, project_id) REFERENCES projects(tenant_id, project_id)
            );
            CREATE INDEX IF NOT EXISTS idx_documents_project
                ON documents(tenant_id, project_id, created_at);
            CREATE TABLE IF NOT EXISTS workflow_state (
                document_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                approved_by TEXT,
                approval_timestamp TEXT,
                rejection_reason TEXT,
                FOREIGN KEY (document_id) REFERENCES documents(document_id)
            );
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (user_id, project_id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT,
                details TEXT,
                timestamp TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_tenant_timestamp
                ON audit_log(tenant_id, timestamp DESC);
            CREATE TABLE IF NOT EXISTS stage_taxonomy (
                tenant_id TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                stage_order INTEGER NOT NULL,
                description TEXT,
                PRIMARY KEY (tenant_id, stage_name)
            );
            CREATE TABLE IF NOT EXISTS notes (
                note_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                project_id TEXT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notes_owner
                ON notes(tenant_id, owner_id, updated_at DESC);
            """
        )
        _initialize_default_stages()
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        if "is_org_admin" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN is_org_admin INTEGER NOT NULL DEFAULT 0")
        if "sensitivity_clearance" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN sensitivity_clearance INTEGER NOT NULL DEFAULT 1")
        for column in ("full_name", "organization", "team_name", "job_title", "manager_email"):
            if column not in columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
        document_columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
        if "visible_to_teams" not in document_columns:
            connection.execute("ALTER TABLE documents ADD COLUMN visible_to_teams TEXT NOT NULL DEFAULT '[]'")
        if "uploaded_by" not in document_columns:
            connection.execute("ALTER TABLE documents ADD COLUMN uploaded_by TEXT")
        project_columns = {row[1] for row in connection.execute("PRAGMA table_info(projects)")}
        if "owner_id" not in project_columns:
            connection.execute("ALTER TABLE projects ADD COLUMN owner_id TEXT")


def create_user(
    *, username: str, password_hash: str | None, provider: str, provider_subject: str | None,
    full_name: str | None = None, organization: str | None = None,
    team_name: str | None = None, job_title: str | None = None, manager_email: str | None = None,
    is_org_admin: bool = False,
    sensitivity_clearance: int = 1,
) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    user = {
        "user_id": str(uuid4()),
        "username": username,
        "password_hash": password_hash,
        "provider": provider,
        "provider_subject": provider_subject,
        "tenant_id": settings.dev_tenant_id,
        "is_org_admin": int(is_org_admin),
        "sensitivity_clearance": sensitivity_clearance,
        "created_at": timestamp,
        "full_name": full_name,
        "organization": organization,
        "team_name": team_name,
        "job_title": job_title,
        "manager_email": manager_email,
    }
    with _connect() as connection:
        connection.execute(
                """INSERT INTO users
                    (user_id, username, password_hash, provider, provider_subject, tenant_id, is_org_admin, sensitivity_clearance, created_at,
                     full_name, organization, team_name, job_title, manager_email)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(user.values()),
        )
    return user


def get_user_by_username(username: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_provider_subject(provider: str, provider_subject: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE provider = ? AND provider_subject = ?",
            (provider, provider_subject),
        ).fetchone()
    return dict(row) if row else None


def link_user_provider(user_id: str, provider: str, provider_subject: str) -> None:
    """Link an already-registered email account to an external identity."""
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET provider = ?, provider_subject = ? WHERE user_id = ?",
            (provider, provider_subject, user_id),
        )


def get_user_access_context(user_id: str):
    """Resolve a persisted user and project memberships into UserContext."""
    from app.models.schema import UserContext

    user = get_user_by_id(user_id)
    if not user:
        return None
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT ur.project_id, ur.role
            FROM user_roles ur
            JOIN projects p ON p.project_id = ur.project_id
            JOIN users u ON u.user_id = ur.user_id AND u.tenant_id = p.tenant_id
            WHERE ur.user_id = ? AND p.tenant_id = ?
            """,
            (user_id, user["tenant_id"]),
        ).fetchall()
        owned_projects = connection.execute(
            "SELECT project_id FROM projects WHERE tenant_id = ? AND owner_id = ?",
            (user["tenant_id"], user_id),
        ).fetchall()
    project_roles = {row["project_id"]: row["role"] for row in rows}
    for project in owned_projects:
        project_roles.setdefault(project["project_id"], "member")
    team_memberships = {
        project_id: [user["team_name"]]
        for project_id in project_roles
        if user.get("team_name")
    }
    role = "admin" if user.get("is_org_admin") or any(row["role"] == "admin" for row in rows) else "member"
    if role != "admin" and any(row["role"] == "reviewer" for row in rows):
        role = "reviewer"
    return UserContext(
        user_id=user["user_id"],
        tenant_id=user["tenant_id"],
        is_org_admin=bool(user.get("is_org_admin")),
        role=role,
        project_roles=project_roles,
        team_memberships=team_memberships,
        sensitivity_clearance=user.get("sensitivity_clearance", 1),
    )


def list_users(tenant_id: str) -> list[dict]:
    """List users and their project roles within one tenant."""
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT u.user_id, u.username, u.full_name, u.team_name, u.is_org_admin,
                   ur.project_id, ur.role
            FROM users u
            LEFT JOIN user_roles ur ON ur.user_id = u.user_id
            WHERE u.tenant_id = ?
            ORDER BY u.username, ur.project_id
            """,
            (tenant_id,),
        ).fetchall()
    users: dict[str, dict] = {}
    for row in rows:
        user = users.setdefault(row["user_id"], {
            "user_id": row["user_id"], "username": row["username"],
            "full_name": row["full_name"], "team_name": row["team_name"],
            "is_org_admin": bool(row["is_org_admin"]), "roles": [],
        })
        if row["project_id"]:
            user["roles"].append({"project_id": row["project_id"], "role": row["role"]})
    return list(users.values())


def record_document(
    *,
    tenant_id: str,
    project_id: str,
    project_name: str,
    document_id: str,
    filename: str,
    stored_path: str,
    stage: str,
    doc_type: str,
    sensitivity_level: int,
    chunk_count: int,
    visible_to_teams: list[str] | None = None,
    uploaded_by: str | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO projects (tenant_id, project_id, project_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, project_id) DO UPDATE SET
                project_name = excluded.project_name,
                updated_at = excluded.updated_at
            """,
            (tenant_id, project_id, project_name, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO documents (
                document_id, tenant_id, project_id, filename, stored_path,
                stage, doc_type, sensitivity_level, visible_to_teams, uploaded_by, chunk_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO NOTHING
            """,
            (
                document_id,
                tenant_id,
                project_id,
                filename,
                stored_path,
                stage,
                doc_type,
                sensitivity_level,
                json.dumps(visible_to_teams or []),
                uploaded_by,
                chunk_count,
                timestamp,
            ),
        )


def list_projects(tenant_id: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT p.project_id, p.project_name, COUNT(d.document_id) AS document_count
            FROM projects p
            LEFT JOIN documents d ON d.tenant_id = p.tenant_id AND d.project_id = p.project_id
            WHERE p.tenant_id = ?
            GROUP BY p.tenant_id, p.project_id, p.project_name
            ORDER BY p.updated_at DESC
            """,
            (tenant_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def create_project(tenant_id: str, project_id: str, project_name: str, owner_id: str) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO projects (tenant_id, project_id, project_name, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, project_id, project_name, owner_id, timestamp, timestamp),
        )
        connection.execute(
            "INSERT INTO user_roles (user_id, project_id, role) VALUES (?, ?, 'member')",
            (owner_id, project_id),
        )
    return {"project_id": project_id, "project_name": project_name, "owner_id": owner_id, "document_count": 0}


def create_note(tenant_id: str, owner_id: str, title: str, content: str, project_id: str | None = None) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    note = {"note_id": str(uuid4()), "tenant_id": tenant_id, "owner_id": owner_id, "project_id": project_id, "title": title, "content": content, "created_at": timestamp, "updated_at": timestamp}
    with _connect() as connection:
        connection.execute(
            "INSERT INTO notes (note_id, tenant_id, owner_id, project_id, title, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            tuple(note.values()),
        )
    return note


def list_notes(tenant_id: str, owner_id: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM notes WHERE tenant_id = ? AND owner_id = ? ORDER BY updated_at DESC",
            (tenant_id, owner_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_project(tenant_id: str, project_id: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM projects WHERE tenant_id = ? AND project_id = ?",
            (tenant_id, project_id),
        ).fetchone()
    return dict(row) if row else None


def list_documents(tenant_id: str, project_id: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT d.document_id, d.project_id, d.filename, d.stage, d.doc_type,
                   d.sensitivity_level, d.chunk_count, d.created_at,
                   d.visible_to_teams, d.uploaded_by,
                   COALESCE(w.state, 'draft') AS workflow_state
            FROM documents d
            LEFT JOIN workflow_state w ON d.document_id = w.document_id
            WHERE d.tenant_id = ? AND d.project_id = ?
            ORDER BY d.created_at DESC
            """,
            (tenant_id, project_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_document(tenant_id: str, document_id: str) -> dict | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT d.*, COALESCE(w.state, 'draft') AS workflow_state
            FROM documents d
            LEFT JOIN workflow_state w ON w.document_id = d.document_id
            WHERE d.tenant_id = ? AND d.document_id = ?
            """,
            (tenant_id, document_id),
        ).fetchone()
    return dict(row) if row else None


def _initialize_default_stages() -> None:
    """Ensure default SDLC stages exist for each tenant."""
    default_stages = [
        ("Intake", 0),
        ("Discovery", 1),
        ("Requirements", 2),
        ("Planning", 3),
        ("Architecture", 4),
        ("Design", 5),
        ("Development", 6),
        ("Integration", 7),
        ("Quality Assurance", 8),
        ("User Acceptance Testing", 9),
        ("Release", 10),
        ("Operations", 11),
        ("Maintenance", 12),
        ("Retirement", 13),
    ]
    with _connect() as connection:
        for stage_name, order in default_stages:
            connection.execute(
                "INSERT OR IGNORE INTO stage_taxonomy (tenant_id, stage_name, stage_order, description) VALUES (?, ?, ?, ?)",
                (settings.dev_tenant_id, stage_name, order, f"SDLC stage: {stage_name}"),
            )


def get_valid_stages(tenant_id: str) -> list[str]:
    """Get valid SDLC stages for a tenant, ordered by sequence."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT stage_name FROM stage_taxonomy WHERE tenant_id = ? ORDER BY stage_order",
            (tenant_id,),
        ).fetchall()
    return [row[0] for row in rows]


def get_user_role(user_id: str, project_id: str) -> str | None:
    """Get a user's role in a specific project (member, reviewer, admin)."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT role FROM user_roles WHERE user_id = ? AND project_id = ?",
            (user_id, project_id),
        ).fetchone()
    return row[0] if row else None


def set_user_role(user_id: str, project_id: str, role: str) -> None:
    """Assign a role to a user in a project."""
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO user_roles (user_id, project_id, role) VALUES (?, ?, ?)",
            (user_id, project_id, role),
        )


def update_user_access(
    user_id: str,
    project_id: str | None = None,
    role: str | None = None,
    team_name: str | None = None,
    sensitivity_clearance: int | None = None,
    is_org_admin: bool | None = None,
) -> None:
    """Update persisted RBAC/ABAC attributes for a tenant user."""
    with _connect() as connection:
        if team_name is not None or sensitivity_clearance is not None or is_org_admin is not None:
            fields = []
            values = []
            if team_name is not None:
                fields.append("team_name = ?")
                values.append(team_name)
            if sensitivity_clearance is not None:
                fields.append("sensitivity_clearance = ?")
                values.append(sensitivity_clearance)
            if is_org_admin is not None:
                fields.append("is_org_admin = ?")
                values.append(int(is_org_admin))
            values.append(user_id)
            connection.execute(f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?", values)
        if project_id and role:
            connection.execute(
                "INSERT OR REPLACE INTO user_roles (user_id, project_id, role) VALUES (?, ?, ?)",
                (user_id, project_id, role),
            )


def get_document_workflow_state(document_id: str) -> str:
    """Get the current approval workflow state of a document."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT state FROM workflow_state WHERE document_id = ?",
            (document_id,),
        ).fetchone()
    return row[0] if row else "draft"


def submit_document(document_id: str) -> None:
    """Move a draft into the approval queue."""
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO workflow_state (document_id, state) VALUES (?, ?)",
            (document_id, "pending_review"),
        )


def approve_document(document_id: str, approved_by: str) -> None:
    """Mark a document as approved."""
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO workflow_state (document_id, state, approved_by, approval_timestamp) VALUES (?, ?, ?, ?)",
            (document_id, "approved", approved_by, timestamp),
        )


def reject_document(document_id: str, rejection_reason: str) -> None:
    """Mark a document as rejected."""
    with _connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO workflow_state (document_id, state, rejection_reason) VALUES (?, ?, ?)",
            (document_id, "rejected", rejection_reason),
        )


def audit_log(tenant_id: str, user_id: str, action: str, resource_type: str, resource_id: str | None = None, details: str | None = None) -> None:
    """Log an audit event."""
    timestamp = datetime.now(timezone.utc).isoformat()
    log_id = str(uuid4())
    with _connect() as connection:
        connection.execute(
            "INSERT INTO audit_log (log_id, tenant_id, user_id, action, resource_type, resource_id, details, timestamp, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (log_id, tenant_id, user_id, action, resource_type, resource_id, details, timestamp, timestamp),
        )


def get_audit_log(tenant_id: str, limit: int = 100) -> list[dict]:
    """Retrieve audit log entries for a tenant."""
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM audit_log WHERE tenant_id = ? ORDER BY timestamp DESC LIMIT ?",
            (tenant_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def list_all_documents(tenant_id: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT d.document_id, d.project_id, COALESCE(p.project_name, d.project_id) AS project_name,
                   d.filename, d.stored_path, d.stage, d.doc_type, d.sensitivity_level,
                     d.chunk_count, d.created_at, d.visible_to_teams, d.uploaded_by,
                     COALESCE(w.state, 'draft') AS workflow_state
            FROM documents d
            LEFT JOIN projects p ON p.tenant_id = d.tenant_id AND p.project_id = d.project_id
                 LEFT JOIN workflow_state w ON w.document_id = d.document_id
            WHERE d.tenant_id = ?
            ORDER BY d.created_at DESC
            """,
            (tenant_id,),
        ).fetchall()
    return [dict(row) for row in rows]
