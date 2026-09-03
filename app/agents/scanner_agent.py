"""Scanner Agent — deterministic score + revision workflow using Agno + Groq."""

from __future__ import annotations

import os

from agno.agent import Agent
from agno.models.groq import Groq

from app.services.document_workflow import extract_document_context, reform_document, score_document
from app.tools.document_tools import reform_document_tool, score_document_tool


def create_scanner_agent() -> Agent:
    api_key = os.getenv("GROQ_API_KEY")
    model = Groq(id="openai/gpt-oss-20b", api_key=api_key or "demo-key")
    return Agent(
        name="Scanner Agent",
        model=model,
        tools=[score_document_tool, reform_document_tool],
        instructions=(
            "You are the Scanner Agent. Mandatory workflow:\n"
            "1. Always call the score_document tool before answering with a score.\n"
            "2. Use the tool output as the score and rationale.\n"
            "3. If the total is below 36, create a revised suggestion using the reform_document tool.\n"
            "4. Never invent a score; never estimate one from memory.\n"
            "5. If the score is clean, ask for explicit confirmation before saving the document."
        ),
    )


def run_scanning_agent(message: str, state: dict | None = None) -> dict:
    state = state or {}
    result = {
        "response": None,
        "tools": [],
        "state": state,
    }
    document_text = state.get("current_content") or message
    info = extract_document_context(message)
    document_type = state.get("document_type") or info.get("document_type") or "General Document"
    project_stage = state.get("project_stage") or info.get("project_stage") or "Requirements"
    score = score_document(document_text, document_type, project_stage)

    try:
        agent = create_scanner_agent()
        context = (
            "Score this document using the required rubric and show the actual tool result.\n"
            f"Document type: {document_type}\n"
            f"Project stage: {project_stage}\n"
            f"Current content:\n{document_text}\n"
        )
        run_output = agent.run(context)
        result["response"] = getattr(run_output, "content", str(run_output))
        result["tools"] = getattr(run_output, "tools", []) or []
        if result["tools"]:
            tool_result = result["tools"][0]
            if hasattr(tool_result, "result"):
                score = tool_result.result
    except Exception:
        pass

    if score.get("passed"):
        result["response"] = (
            f"Scan passed: {score['total']}/60. "
            "The score and criteria are based on the actual rubric output. "
            "Confirm with 'save' to store the final document."
        )
    else:
        revised = reform_document(document_text, document_type, project_stage, score)
        result["response"] = (
            f"Scan result: {score['total']}/60, below the 36/60 threshold.\n"
            f"Criteria: {score['criteria']}\n\n"
            "Suggested revision (pending human review, not final):\n\n"
            f"{revised}"
        )
        result["revised_document"] = revised
    result["score"] = score
    return result
