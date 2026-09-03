"""Qdrant collection-per-tenant setup — hybrid dense+sparse vectors.

Per finalized decision: collection-per-tenant for structural isolation
(safer for sensitive data) over a shared collection filtered by metadata.
"""

from qdrant_client import QdrantClient, models

from app.config import settings


def collection_name(tenant_id: str) -> str:
    return f"tenant_{tenant_id}"


def create_tenant_collection(client: QdrantClient, tenant_id: str) -> None:
    """Create a new tenant's collection. Call once at tenant onboarding.

    Every chunk inserted later must populate BOTH named vectors:
    "dense" (semantic embedding) and "sparse" (BM25/SPLADE-style).
    """
    client.create_collection(
        collection_name=collection_name(tenant_id),
        vectors_config={
            "dense": models.VectorParams(
                size=settings.dense_embedding_dim,
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(
                index=models.SparseIndexParams(on_disk=False),
            ),
        },
    )

    # Payload indexes for every field used in build_access_filter() —
    # required for filter performance at scale, not just correctness.
    keyword_fields = ("project_id", "stage", "visible_to_teams", "doc_type")
    for field_name in keyword_fields:
        client.create_payload_index(
            collection_name=collection_name(tenant_id),
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    client.create_payload_index(
        collection_name=collection_name(tenant_id),
        field_name="sensitivity_level",
        field_schema=models.PayloadSchemaType.INTEGER,
    )
