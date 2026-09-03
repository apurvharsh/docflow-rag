"""Compatibility exports for the app's legacy agent module and new Agno runtime."""

from app.agents.drafting_agent import DraftingAgent, create_drafting_agent, run_drafting_agent
from app.agents.gap_detection_agent import GapDetectionAgent
from app.agents.general_query_agent import GeneralQueryAgent
from app.agents.scanner_agent import create_scanner_agent, run_scanning_agent

DraftingAgent = DraftingAgent

__all__ = [
    "DraftingAgent",
    "create_drafting_agent",
    "run_drafting_agent",
    "GapDetectionAgent",
    "GeneralQueryAgent",
    "create_scanner_agent",
    "run_scanning_agent",
]
