"""Gap-Detection Agent — Identifies missing documents across SDLC stages.

The Gap-Detection Agent analyzes the existing documents in a project,
compares them against the standard SDLC stage requirements, and flags
missing documentation that should be created or uploaded.
"""

from typing import Optional
from app.models.schema import UserContext
from app.retrieval.embeddings import generate_answer


class GapDetectionAgent:
    """Identifies gaps in project documentation."""
    
    STAGE_REQUIREMENTS = {
        "Intake": ["Project Charter", "Business Case", "Stakeholder List"],
        "Discovery": ["Market Analysis", "User Research", "Competitive Analysis"],
        "Requirements": ["Functional Requirements", "User Stories", "Acceptance Criteria"],
        "Design": ["Architecture Design", "Database Schema", "UI/UX Mockups", "API Design"],
        "Development": ["Code Structure", "API Documentation", "Configuration Guide"],
        "Quality Assurance": ["Test Plan", "Test Cases", "Coverage Report"],
        "User Acceptance Testing": ["UAT Scripts", "Sign-off Form"],
        "Release": ["Release Notes", "Deployment Guide", "Rollback Plan"],
    }
    
    @staticmethod
    def detect_gaps(
        project_id: str,
        stages: list[str],
        existing_docs: list[dict],
    ) -> dict:
        """Detect missing documentation across project stages.
        
        Args:
            project_id: The project to analyze
            stages: List of SDLC stages for this project
            existing_docs: List of existing documents
            
        Returns:
            Dictionary with missing docs per stage and gap analysis
        """
        existing_titles = {doc.get("filename", "").lower() or doc.get("doc_type", "").lower() for doc in existing_docs}
        gaps = {}
        
        for stage in stages:
            required = GapDetectionAgent.STAGE_REQUIREMENTS.get(stage, [])
            stage_gaps = []
            
            for req in required:
                # Simple substring matching for gap detection
                if not any(req.lower() in title.lower() for title in existing_titles):
                    stage_gaps.append(req)
            
            if stage_gaps:
                gaps[stage] = stage_gaps
        
        return {
            "project_id": project_id,
            "total_gaps": sum(len(v) for v in gaps.values()),
            "gaps_by_stage": gaps,
            "missing_stages": [s for s in stages if not any(doc.get("stage") == s for doc in existing_docs)],
        }
    
    @staticmethod
    def generate_gap_report(
        project_id: str,
        gaps: dict,
        existing_docs: list[dict],
    ) -> str:
        """Generate a human-readable gap analysis report.
        
        Args:
            project_id: The project
            gaps: Dictionary of gaps from detect_gaps()
            existing_docs: List of existing documents
            
        Returns:
            Formatted gap report as Markdown
        """
        total_gaps = gaps.get("total_gaps", 0)
        gaps_by_stage = gaps.get("gaps_by_stage", {})
        
        if not gaps_by_stage:
            return f"✅ Project '{project_id}' has complete documentation for all stages."
        
        report = f"## Documentation Gap Analysis: {project_id}\n\n"
        report += f"**Status:** {total_gaps} missing documents\n\n"
        
        for stage, missing_docs in gaps_by_stage.items():
            report += f"### {stage} Phase\n"
            report += f"**Missing ({len(missing_docs)} items):**\n"
            for doc in missing_docs:
                report += f"- [ ] {doc}\n"
            report += "\n"
        
        report += f"\n**Total Documents:** {len(existing_docs)}\n"
        report += f"**Completion:** {max(0, 100 - int(100 * total_gaps / (total_gaps + len(existing_docs)))):.0f}%\n"
        
        return report
