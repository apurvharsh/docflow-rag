"""CLI runtime for the deterministic command-driven draft/scan workflow."""

from __future__ import annotations

from app.agents.drafting_agent import run_drafting_agent
from app.agents.scanner_agent import run_scanning_agent
from app.services.document_workflow import (
    build_context_summary,
    extract_document_context,
    save_document,
)


def create_default_state() -> dict:
    return {
        "active_agent": None,
        "document_type": None,
        "project_stage": None,
        "draft_status": "new",
        "current_content": "",
        "ready_for_scan": False,
        "scan_result": None,
        "saved_document": None,
    }


def _command_response(message: str, state: dict) -> dict:
    text = message.strip()
    if text in {"/draft", "/scan", "/rag", "/query"}:
        state["active_agent"] = text.lstrip("/")
        if state["active_agent"] == "draft":
            return {"response": "Switched to Drafting Agent. Tell me what document you want to draft.", "state": state}
        if state["active_agent"] == "scan":
            return {"response": "Switched to Scanner Agent. Paste or describe the document to score.", "state": state}
        return {"response": "RAG Agent and Query Agent are stubs for Phase 2. Vector indexing and metadata Q&A are not active yet.", "state": state}
    return {"response": None, "state": state}


def handle_cli_message(message: str, state: dict | None = None) -> dict:
    state = state or create_default_state()
    text = (message or "").strip()
    if not text:
        return {"response": "Please enter a message or a command.", "state": state}

    command_result = _command_response(text, state)
    if command_result["response"] is not None:
        return command_result

    active = state.get("active_agent")

    if active == "draft":
        info = extract_document_context(text)
        state["document_type"] = state.get("document_type") or info.get("document_type")
        state["project_stage"] = state.get("project_stage") or info.get("project_stage")

        if state.get("document_type") in (None, "General Document") and "document type" not in text.lower():
            return {
                "response": "I need a document type and project stage to draft accurately. Example: 'Draft a PRD for Requirements'.",
                "state": state,
            }

        if "approve" in text.lower() or "ready for scan" in text.lower():
            state["ready_for_scan"] = True
            state["draft_status"] = "ready_for_scan"
            return {"response": "Draft marked ready for scanning. Switch to /scan when you want the review in motion.", "state": state}

        result = run_drafting_agent(text, state)
        draft_text = result["response"]
        state["current_content"] = draft_text
        state["draft_status"] = "drafted"
        state["document_type"] = state.get("document_type") or info.get("document_type")
        state["project_stage"] = state.get("project_stage") or info.get("project_stage")
        summary = build_context_summary(state)
        return {"response": f"{summary}\nDraft created:\n\n{draft_text}", "state": state}

    if active == "scan":
        info = extract_document_context(text)
        state["document_type"] = state.get("document_type") or info.get("document_type")
        state["project_stage"] = state.get("project_stage") or info.get("project_stage")
        document_text = state.get("current_content") or text

        if not document_text or not document_text.strip():
            return {"response": "There is no document to scan yet. Draft one first or paste a document to review.", "state": state}

        result = run_scanning_agent(text, state)
        score = result.get("score")
        state["scan_result"] = score
        if score and score.get("passed"):
            if "save" in text.lower() or "confirm" in text.lower() or "approved" in text.lower():
                saved = save_document(document_text, state.get("document_type") or "General Document", state.get("project_stage") or "Requirements")
                state["saved_document"] = saved
                state["draft_status"] = "saved"
                return {"response": f"Document passed scan with {score['total']}/60. Saved to {saved['path']}", "state": state}
            return {"response": result["response"], "state": state}

        revised = result.get("revised_document") or ""
        state["current_content"] = revised
        state["draft_status"] = "needs_revision"
        return {"response": result["response"], "state": state}

    if active in {"rag", "query"}:
        return {"response": "RAG and Query are stubs for Phase 2; vector indexing and metadata Q&A are not active yet.", "state": state}

    return {"response": "Choose a command first: /draft, /scan, /rag, or /query.", "state": state}
