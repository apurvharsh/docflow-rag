"""Thin Agno tool wrappers for the drafting and scanning workflow."""

from __future__ import annotations

from agno.tools import tool

from app.services.document_workflow import (
    extract_document_context,
    generate_draft,
    reform_document,
    save_document,
    score_document,
)


@tool(name="extract_document_context", description="Extract a document type and project stage from a user message.")
def extract_document_context_tool(message: str):
    return extract_document_context(message)


@tool(name="generate_draft", description="Draft a document based on type, stage, and optional template content.")
def generate_draft_tool(document_type: str, project_stage: str, user_prompt: str = "", template: str | None = None, current_content: str | None = None):
    return generate_draft(document_type, project_stage, user_prompt=user_prompt, template=template, current_content=current_content)


@tool(name="score_document", description="Score a document using the required rubric: structure, completeness, labeling accuracy.")
def score_document_tool(document_text: str, document_type: str, project_stage: str):
    return score_document(document_text, document_type, project_stage)


@tool(name="reform_document", description="Create a revised version of a document when the score is below threshold.")
def reform_document_tool(document_text: str, document_type: str, project_stage: str, score_result: dict | None = None):
    return reform_document(document_text, document_type, project_stage, score_result)


@tool(name="save_document", description="Save a final approved draft into the local drafts folder.")
def save_document_tool(document_text: str, document_type: str, project_stage: str, filename: str | None = None):
    return save_document(document_text, document_type, project_stage, filename=filename)
