"""General Query Agent — Handles multi-turn reasoning across project documents.

The General Query Agent processes custom user queries, performs multi-step reasoning
over the project knowledge base, and provides grounded answers with citations.
It can handle complex questions that require synthesizing information from multiple
documents.
"""

from typing import Optional
from app.models.schema import UserContext
from app.retrieval.embeddings import generate_answer
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.embeddings import embed_dense, embed_sparse
from qdrant_client import QdrantClient


class GeneralQueryAgent:
    """Handles complex, multi-step queries across project documents."""
    
    @staticmethod
    def process_query(
        query: str,
        hits: list[dict],
        project_context: Optional[str] = None,
    ) -> str:
        """Process a complex query using retrieved documents.
        
        Args:
            query: The user's question
            hits: Retrieved document chunks from hybrid search
            project_context: Optional context about the project
            
        Returns:
            Grounded answer with citations
        """
        if not hits:
            return "I couldn't find relevant information to answer this question."
        
        # Build context from retrieved chunks
        context_parts = []
        for index, hit in enumerate(hits[:5]):  # Use top 5 results
            chunk_text = hit.get("payload", {}).get("chunk_text", "")
            doc_id = hit.get("payload", {}).get("document_id", "unknown")
            section = hit.get("payload", {}).get("section_title", "")
            score = hit.get("score", 0)
            
            context_parts.append(
                f"[Source {index + 1} (relevance: {score:.2f}): {doc_id} - {section}]\n{chunk_text}"
            )
        
        context = "\n\n".join(context_parts)
        
        # Build comprehensive prompt
        prompt = (
            "Answer the following question using ONLY the provided sources. "
            "Cite each source as [Source N]. "
            "If the information needed to answer is not in the sources, say so explicitly.\n\n"
            f"Question: {query}\n\n"
            f"Sources:\n{context}"
        )
        
        if project_context:
            prompt += f"\n\nProject Context:\n{project_context}"
        
        return generate_answer(prompt)
    
    @staticmethod
    def check_answer_completeness(
        answer: str,
        query: str,
        hit_count: int,
    ) -> dict:
        """Analyze answer quality and completeness.
        
        Args:
            answer: The generated answer
            query: The original query
            hit_count: Number of sources used
            
        Returns:
            Analysis dictionary with quality metrics
        """
        is_grounded = "[Source" in answer or "I couldn't find" in answer
        has_citations = answer.count("[Source") >= 1 if hit_count > 0 else True
        
        return {
            "query": query,
            "hit_count": hit_count,
            "is_grounded": is_grounded,
            "has_citations": has_citations,
            "answer_length": len(answer),
            "quality": "high" if is_grounded and has_citations else "medium" if is_grounded else "low",
        }
    
    @staticmethod
    def suggest_followup_queries(
        query: str,
        answer: str,
    ) -> list[str]:
        """Suggest related follow-up questions.
        
        Args:
            query: Original question
            answer: Generated answer
            
        Returns:
            List of suggested follow-up questions
        """
        prompt = (
            f"Given this question and answer, suggest 3 logical follow-up questions "
            f"that would deepen the understanding of the topic.\n\n"
            f"Original Question: {query}\n"
            f"Answer: {answer}\n\n"
            f"Format as a numbered list."
        )
        
        followups_text = generate_answer(prompt)
        
        # Parse the response to extract questions
        lines = followups_text.strip().split("\n")
        followups = []
        for line in lines:
            # Extract text after numbers like "1.", "2.", etc.
            if line and line[0].isdigit() and "." in line:
                question = line.split(".", 1)[1].strip()
                if question:
                    followups.append(question)
        
        return followups[:3]  # Return up to 3 suggestions
