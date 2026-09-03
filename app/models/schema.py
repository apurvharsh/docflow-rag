"""Shared data shapes: chunk payload (Qdrant) and user context (ABAC)."""

from dataclasses import dataclass, field
from enum import IntEnum


class SensitivityLevel(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


@dataclass
class ChunkPayload:
    """One chunk's metadata, stored in Qdrant payload alongside its vectors.

    Mirrors the tagging scheme shared across all three storage layers
    (S3, Postgres, Qdrant) per the project's finalized storage architecture.
    """

    document_id: str
    project_id: str
    stage: str                     # Intake, Requirements, Design, ...
    doc_type: str                  # PRD, TestPlan, DesignDoc, ...
    section_title: str             # from structure-scanner parse
    visible_to_teams: list[str] = field(default_factory=list)  # [] = no restriction
    sensitivity_level: int = SensitivityLevel.INTERNAL
    workflow_state: str = "draft"
    chunk_text: str = ""           # includes prepended contextual header
    chunk_index: int = 0

    def to_qdrant_payload(self) -> dict:
        return {
            "document_id": self.document_id,
            "project_id": self.project_id,
            "stage": self.stage,
            "doc_type": self.doc_type,
            "section_title": self.section_title,
            "visible_to_teams": self.visible_to_teams,
            "sensitivity_level": int(self.sensitivity_level),
            "workflow_state": self.workflow_state,
            "chunk_text": self.chunk_text,
            "chunk_index": self.chunk_index,
        }


@dataclass
class UserContext:
    """Resolved ABAC identity for the requesting user, built by the auth layer."""

    user_id: str
    tenant_id: str
    is_org_admin: bool
    role: str = "member"
    project_roles: dict[str, str] = field(default_factory=dict)        # project_id -> role
    team_memberships: dict[str, list[str]] = field(default_factory=dict)  # project_id -> [team_ids]
    sensitivity_clearance: int = SensitivityLevel.INTERNAL
