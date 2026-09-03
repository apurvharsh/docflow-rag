"""Service-layer workflow for drafting, scanning, and saving project documents."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
DRAFTS_DIR = BASE_DIR.parent / "drafts"
DRAFTS_DIR.mkdir(exist_ok=True, parents=True)

DOCUMENT_TYPE_ALIASES = {
    "PRD": ["prd", "product requirements document", "product requirement doc"],
    "BRD": ["brd", "business requirements document"],
    "SRS": ["srs", "software requirements specification"],
    "ADR": ["adr", "architecture decision record"],
    "API Specification": ["api specification", "api spec", "openapi", "rest api"],
    "Project Plan": ["project plan", "implementation plan"],
    "Design Document": ["design document", "technical design"],
    "Risk Register": ["risk register", "risks"],
    "Test Plan": ["test plan"],
    "Runbook": ["runbook", "operations runbook"],
    "Release Notes": ["release notes"],
    "Proposal": ["proposal", "statement of work"],
    "Meeting Notes": ["meeting notes", "meeting summary"],
    "Other": ["other document", "general doc", "document"],
}

STAGE_ALIASES = {
    "Intake": ["intake"],
    "Discovery": ["discovery", "research"],
    "Requirements": ["requirements", "requirement"],
    "Planning": ["planning", "plan"],
    "Architecture": ["architecture", "architectural"],
    "Design": ["design"],
    "Development": ["development", "build"],
    "Integration": ["integration"],
    "Quality Assurance": ["quality assurance", "qa", "testing"],
    "User Acceptance Testing": ["uat", "user acceptance testing"],
    "Release": ["release"],
    "Operations": ["operations", "ops"],
    "Maintenance": ["maintenance"],
    "Retirement": ["retirement"],
}


def _match_aliases(message: str, aliases: dict[str, list[str]]) -> str | None:
    lowered = message.lower()
    for label, patterns in aliases.items():
        for pattern in patterns:
            if pattern in lowered:
                return label
    return None


def extract_document_context(message: str) -> dict[str, Any]:
    text = (message or "").strip()
    stage = _match_aliases(text, STAGE_ALIASES)
    doc_type = _match_aliases(text, DOCUMENT_TYPE_ALIASES)

    if not doc_type:
        for pattern, label in (
            (r"\b(\w+\s+requirements? document)\b", "PRD"),
            (r"\b(\w+\s+requirements? specification)\b", "SRS"),
            (r"\b(architecture decision record)\b", "ADR"),
            (r"\b(api specification|api spec)\b", "API Specification"),
            (r"\b(test plan|test case)\b", "Test Plan"),
        ):
            if re.search(pattern, text, flags=re.IGNORECASE):
                doc_type = label
                break

    if not stage:
        stage = "Unspecified"
    if not doc_type:
        doc_type = "General Document"

    return {
        "document_type": doc_type,
        "project_stage": stage,
        "template": _infer_template(text, doc_type, stage),
        "raw_message": text,
    }


def _infer_template(message: str, doc_type: str, stage: str) -> str | None:
    lowered = message.lower()
    for token in ("template", "follow", "use"):
        if token in lowered:
            for part in re.split(r"\btemplate\b|\bfollow\b|\buse\b", message, flags=re.IGNORECASE):
                if part.strip():
                    return part.strip()
    return None


def build_context_summary(context: dict[str, Any]) -> str:
    doc_type = context.get("document_type") or "General Document"
    stage = context.get("project_stage") or "Unspecified"
    status = context.get("draft_status") or "new"
    content_len = len((context.get("current_content") or "").strip())
    return (
        "Active context:\n"
        f"- Document type: {doc_type}\n"
        f"- Project stage: {stage}\n"
        f"- Draft status: {status}\n"
        f"- Current draft length: {content_len} chars\n"
    )


def _fallback_draft(document_type: str, project_stage: str, template: str | None = None, current_content: str | None = None) -> str:
    overview = template or current_content or f"Draft {document_type} for the {project_stage} stage."
    stage_sections = {
        "Intake": ["Purpose", "Stakeholders", "Objectives", "Scope"],
        "Discovery": ["Context", "Research Summary", "Findings", "Open Questions"],
        "Requirements": ["Objective", "User Needs", "Functional Requirements", "Acceptance Criteria"],
        "Planning": ["Plan Overview", "Timeline", "Dependencies", "Risks"],
        "Architecture": ["System Overview", "Key Components", "Interfaces", "Constraints"],
        "Design": ["Design Goals", "Interaction Model", "UI / UX", "Implementation Notes"],
        "Development": ["Build Approach", "Technical Tasks", "Code Ownership", "Validation"],
        "Integration": ["Integration Points", "Contracts", "Dependencies", "Rollout Considerations"],
        "Quality Assurance": ["Test Strategy", "Test Cases", "Exit Criteria", "Defect Handling"],
        "User Acceptance Testing": ["User Scenarios", "Validation Notes", "Sign-off Checklist", "Exit Criteria"],
        "Release": ["Release Plan", "Rollout Steps", "Backward Compatibility", "Roll-back"],
        "Operations": ["Operating Model", "Monitoring", "Ownership", "Support"],
        "Maintenance": ["Maintenance Plan", "Monitoring", "Known Issues", "Update Cadence"],
        "Retirement": ["Retirement Scope", "Migration Notes", "Impact", "Closure Criteria"],
    }
    sections = stage_sections.get(project_stage, ["Overview", "Scope", "Key Details", "Status"])
    document = [
        f"# {document_type} — {project_stage}",
        "",
        f"## Overview",
        f"{overview}",
        "",
    ]
    for idx, section in enumerate(sections, start=1):
        document.append(f"## {section}")
        if section == "Objective" or section == "Overview":
            document.append(f"This document outlines the purpose, scope, and expected outcomes for the {project_stage.lower()} phase.")
        elif section == "Acceptance Criteria":
            document.append("- Requirement is clearly stated.")
            document.append("- The outcome is testable and measurable.")
            document.append("- Sign-off is captured before release.")
        elif section == "Risks":
            document.append("- Risk: missing stakeholder alignment.")
            document.append("- Mitigation: define ownership and decision path.")
        else:
            document.append(f"Document the relevant details for {section.lower()} in this {project_stage.lower()} deliverable.")
        document.append("")
    document.append("## Approval")
    document.append("Ready for review and scan before final sign-off.")
    return "\n".join(document)


def generate_draft(document_type: str, project_stage: str, user_prompt: str = "", template: str | None = None, current_content: str | None = None) -> str:
    if not document_type:
        document_type = "General Document"
    if not project_stage or project_stage == "Unspecified":
        project_stage = "Requirements"
    text = user_prompt.strip() if user_prompt else (current_content or "")
    if text:
        if "edit" in text.lower() or "redraft" in text.lower() or "revise" in text.lower() or current_content:
            return _fallback_draft(document_type, project_stage, template=template or text, current_content=current_content)
    return _fallback_draft(document_type, project_stage, template=template or user_prompt or current_content)


def score_document(document_text: str, document_type: str, project_stage: str) -> dict[str, Any]:
    text = (document_text or "").strip()
    word_count = len(re.findall(r"\S+", text)) if text else 0
    heading_count = len(re.findall(r"^#{1,6}\s+", text, flags=re.MULTILINE))
    bullet_count = len(re.findall(r"^[-*+]\s+", text, flags=re.MULTILINE))
    has_title = bool(re.search(r"^#\s+|^Title\s*:\s*", text, flags=re.MULTILINE))
    has_stage_reference = project_stage.lower() in text.lower() or document_type.lower() in text.lower()

    structural = min(20, 8 + 5 * min(2, heading_count) + (2 if has_title else 0) + (3 if bullet_count >= 2 else 0))
    completeness = min(
        20,
        max(
            0,
            min(
                20,
                6
                + word_count // 20
                + (2 if has_stage_reference else 0)
                + (4 if heading_count >= 2 else 0)
                + (2 if bullet_count >= 2 else 0),
            ),
        ),
    )
    labeling = min(20, 8 + (4 if has_title else 0) + (4 if has_stage_reference else 0) + (4 if heading_count >= 2 else 0))

    criteria = [
        {
            "name": "Structural clarity",
            "score": structural,
            "max_score": 20,
            "minimum": 12,
            "weight": 1,
            "reason": "Checked headings, title, and section organization.",
        },
        {
            "name": "Completeness",
            "score": completeness,
            "max_score": 20,
            "minimum": 12,
            "weight": 1,
            "reason": "Checked how much useful detail is present and whether the required scope is covered.",
        },
        {
            "name": "Labeling accuracy",
            "score": labeling,
            "max_score": 20,
            "minimum": 12,
            "weight": 1.5,
            "reason": "Checked whether the document type and stage are clearly reflected in the content.",
        },
    ]

    total = sum(item["score"] * item["weight"] for item in criteria)
    weighted_max = sum(item["max_score"] * item["weight"] for item in criteria)
    pct = (total / weighted_max) * 100 if weighted_max else 0
    total_points = sum(item["score"] for item in criteria)
    total_threshold = 36
    min_metric_ok = all(item["score"] >= item["minimum"] for item in criteria)
    passed = total_points >= total_threshold and min_metric_ok and pct >= 60
    return {
        "document_type": document_type,
        "project_stage": project_stage,
        "criteria": criteria,
        "total": total_points,
        "threshold": total_threshold,
        "percent": round(pct, 2),
        "passed": passed,
        "clean": passed,
        "status": "clean" if passed else "needs_revision",
        "summary": f"Score: {total_points}/60 ({pct:.2f}%); minimum metric checks: {'pass' if min_metric_ok else 'fail'}.",
    }


def reform_document(document_text: str, document_type: str, project_stage: str, score_result: dict[str, Any] | None = None) -> str:
    cleaned = (document_text or "").strip() or f"{document_type} for {project_stage}"
    sections = [
        f"# {document_type} — {project_stage}",
        "",
        "## Title",
        "A clear title that reflects the document purpose and ownership.",
        "",
        "## Overview",
        "Describe the purpose, business context, and expected result of this document.",
        "",
        "## Scope",
        "- Objective",
        "- In-scope items",
        "- Out-of-scope items",
        "",
        "## Key Details",
        "Capture the main facts, requirements, or process steps that define this deliverable.",
        "",
        "## Acceptance Criteria",
        "- The output is clear and measurable.",
        "- The owner and review path are named.",
        "- The content is aligned to the target stage and document type.",
        "",
        "## Notes",
        "Include open questions, risks, or follow-up actions that still need review.",
    ]
    revised = "\n".join(sections)
    if cleaned and cleaned.lower() not in {"bad text", "n/a"}:
        revised = revised + "\n\n### Original Notes\n" + cleaned
    return revised


def save_document(document_text: str, document_type: str, project_stage: str, filename: str | None = None) -> dict[str, str]:
    safe_name = (filename or f"{document_type.lower().replace(' ', '_')}_{project_stage.lower().replace(' ', '_')}").strip()
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", safe_name)
    path = DRAFTS_DIR / f"{safe_name or 'draft'}.md"
    path.write_text(document_text.strip() + "\n", encoding="utf-8")
    return {"path": str(path), "filename": path.name}


def load_saved_documents() -> list[str]:
    return sorted(p.name for p in DRAFTS_DIR.glob("*.md"))
