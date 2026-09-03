"""hybrid_search() — dense + sparse search, RRF fusion, cross-encoder rerank.

access_filter must come from build_access_filter() and is applied to
BOTH legs of the hybrid search — filtering happens at query time on
every path, never post-retrieval (per finalized architectural decision).
"""

from qdrant_client import QdrantClient, models

from app.config import settings
from app.ingestion.collection_setup import collection_name


def hybrid_search(
    client: QdrantClient,
    tenant_id: str,
    query_text: str,
    dense_vector: list[float],
    sparse_vector: models.SparseVector,
    access_filter: models.Filter,
    top_k_fetch: int | None = None,
    top_k_final: int | None = None,
) -> list[dict]:
    """Run dense + sparse search in parallel, fuse with RRF, rerank, trim."""
    top_k_fetch = top_k_fetch or settings.top_k_fetch
    top_k_final = top_k_final or settings.top_k_final

    dense_hits = _query_points(
        client,
        collection_name=collection_name(tenant_id),
        query=dense_vector,
        using="dense",
        query_filter=access_filter,
        limit=top_k_fetch,
    )
    sparse_hits = _query_points(
        client,
        collection_name=collection_name(tenant_id),
        query=sparse_vector,
        using="sparse",
        query_filter=access_filter,
        limit=top_k_fetch,
    )

    fused = _reciprocal_rank_fusion(dense_hits, sparse_hits)
    reranked = _rerank(query_text, fused[:top_k_fetch])
    return reranked[:top_k_final]


def _query_points(client: QdrantClient, **kwargs):
    return client.query_points(**kwargs).points


def _reciprocal_rank_fusion(dense_hits, sparse_hits, k: int = 60) -> list[dict]:
    """Combine two ranked lists by RRF score: sum(1 / (k + rank + 1))."""
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}

    for rank, hit in enumerate(dense_hits):
        scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (k + rank + 1)
        payloads[hit.id] = hit.payload

    for rank, hit in enumerate(sparse_hits):
        scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (k + rank + 1)
        payloads[hit.id] = hit.payload

    ranked_ids = sorted(scores, key=scores.get, reverse=True)
    return [{"id": i, "score": scores[i], "payload": payloads[i]} for i in ranked_ids]


def _rerank(query_text: str, candidates: list[dict]) -> list[dict]:
    """Return fused candidates in score order.

    RRF is the reranker for the API-backed MVP; the fused score is already
    based on both semantic and lexical rankings.
    """
    return sorted(candidates, key=lambda candidate: candidate["score"], reverse=True)
