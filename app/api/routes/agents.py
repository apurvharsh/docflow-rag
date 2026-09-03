"""Multi-agent orchestration routes."""

from fastapi import APIRouter, Depends, HTTPException
from qdrant_client import QdrantClient

from app.api.dependencies import get_current_user, get_optional_user, get_qdrant_client
from app.agents import DraftingAgent, GapDetectionAgent, GeneralQueryAgent
from app.database import list_documents, get_valid_stages, audit_log
from app.models.requests import GenerateOutlineRequest, AskRequest
from app.models.responses import GenerateOutlineResponse, GapAnalysisResponse, FollowupSuggestions
from app.models.schema import UserContext
from app.retrieval.access_filter import build_access_filter
from app.retrieval.embeddings import embed_dense, embed_sparse, generate_answer
from app.retrieval.hybrid_search import hybrid_search

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/drafting/outline", response_model=GenerateOutlineResponse)
def agent_generate_outline(
    request: GenerateOutlineRequest,
    user: UserContext = Depends(get_current_user),
):
    """Generate a documentation outline for a project stage (Drafting Agent)."""
    try:
        documents = list_documents(user.tenant_id, request.project_id)
        outline = DraftingAgent.generate_document_outline(
            project_id=request.project_id,
            stage=request.stage,
            existing_docs=documents,
            user=user,
        )
        audit_log(user.tenant_id, user.user_id, "AGENT_CALL", "drafting_agent", 
                 request.project_id, f"stage={request.stage}")
        return GenerateOutlineResponse(outline=outline, stage=request.stage)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/gap-detection/analyze", response_model=GapAnalysisResponse)
def agent_analyze_gaps(
    project_id: str,
    user: UserContext = Depends(get_current_user),
):
    """Analyze documentation gaps in a project (Gap-Detection Agent)."""
    try:
        stages = get_valid_stages(user.tenant_id)
        documents = list_documents(user.tenant_id, project_id)
        
        gaps = GapDetectionAgent.detect_gaps(
            project_id=project_id,
            stages=stages,
            existing_docs=documents,
        )
        
        gap_report = GapDetectionAgent.generate_gap_report(
            project_id=project_id,
            gaps=gaps,
            existing_docs=documents,
        )
        
        audit_log(user.tenant_id, user.user_id, "AGENT_CALL", "gap_detection_agent", 
                 project_id, f"gaps_found={gaps['total_gaps']}")
        
        return GapAnalysisResponse(
            project_id=project_id,
            total_gaps=gaps["total_gaps"],
            gaps_by_stage=gaps["gaps_by_stage"],
            gap_report=gap_report,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/query/followups", response_model=FollowupSuggestions)
def agent_suggest_followups(
    request: AskRequest,
    user: UserContext = Depends(get_optional_user),
    client: QdrantClient = Depends(get_qdrant_client),
):
    """Suggest follow-up questions based on an answer (General Query Agent)."""
    try:
        access_filter = build_access_filter(user, project_id=request.project_id)
        hits = hybrid_search(
            client=client,
            tenant_id=user.tenant_id,
            query_text=request.query,
            dense_vector=embed_dense(request.query, task_type="RETRIEVAL_QUERY"),
            sparse_vector=embed_sparse(request.query),
            access_filter=access_filter,
        )
        
        if not hits:
            return FollowupSuggestions(followup_questions=[])
        
        # Generate initial answer
        context = "\n\n".join(
            f"[Source {index + 1}: {hit['payload']['document_id']}]\n{hit['payload']['chunk_text']}"
            for index, hit in enumerate(hits[:3])
        )
        answer = generate_answer(f"Briefly answer: {request.query}\n\nContext:\n{context}")
        
        # Suggest follow-ups
        followups = GeneralQueryAgent.suggest_followup_queries(request.query, answer)
        
        audit_log(user.tenant_id, user.user_id, "AGENT_CALL", "query_agent", 
                 request.project_id or "all", f"followups={len(followups)}")
        
        return FollowupSuggestions(followup_questions=followups)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/stages")
def get_available_stages(user: UserContext = Depends(get_optional_user)):
    """Get valid SDLC stages for the tenant."""
    return get_valid_stages(user.tenant_id)
