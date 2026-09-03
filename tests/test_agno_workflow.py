from app.services.document_workflow import (
    extract_document_context,
    score_document,
    reform_document,
)


def test_extracts_document_type_and_stage_from_message():
    payload = extract_document_context("Draft a PRD for the Requirements stage")
    assert payload["document_type"] == "PRD"
    assert payload["project_stage"] == "Requirements"


def test_score_document_uses_actual_rubric():
    result = score_document(
        "Title\nOverview\nGoals\nScope\nAcceptance Criteria\nUser stories\nRisks\n",
        "PRD",
        "Requirements",
    )
    assert result["total"] >= 0
    assert result["threshold"] == 36
    assert result["passed"] in {True, False}
    assert "criteria" in result
    assert all("score" in criterion for criterion in result["criteria"])


def test_reform_document_returns_revised_text_when_below_threshold():
    result = score_document("Bad text", "PRD", "Requirements")
    revised = reform_document("Bad text", "PRD", "Requirements", result)
    assert isinstance(revised, str)
    assert len(revised) > 0
    assert "Title" in revised or "Overview" in revised


def test_metric_minimums_block_low_labeling_accuracy_even_when_total_is_high():
    result = score_document(
        "# PRD — Requirements\n## Overview\nThis PRD defines the onboarding flow, stakeholder approval steps, and the release acceptance criteria for the Requirements stage.\n\n## Scope\n- Onboard new users\n- Track approval workflow\n- Capture measurable completion criteria\n\n## Requirements\n- Users can register with an email and password\n- Admins review the workflow before approval\n- Error states are visible and testable\n\n## Acceptance Criteria\n- Each step is measurable\n- Sign-off is captured before release\n- Review outcome is documented\n",
        "PRD",
        "Requirements",
    )
    assert result["criteria"][0]["score"] >= 12
    assert result["criteria"][1]["score"] >= 12
    assert result["criteria"][2]["score"] >= 12
    assert result["passed"] is True

    score = score_document("Bad text", "PRD", "Requirements")
    assert score["criteria"][2]["score"] < 12
    assert score["passed"] is False

    min_thresholds = {item["name"]: item["minimum"] for item in score["criteria"]}
    assert min_thresholds["Structural clarity"] >= 12
    assert min_thresholds["Completeness"] >= 12
    assert min_thresholds["Labeling accuracy"] >= 12
