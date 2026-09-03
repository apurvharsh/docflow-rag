"""Embed and persist chunks in a tenant-isolated Qdrant collection."""

from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.ingestion.collection_setup import collection_name, create_tenant_collection
from app.models.schema import ChunkPayload
from app.retrieval.embeddings import embed_dense, embed_sparse


def index_chunks(client: QdrantClient, tenant_id: str, chunks: list[ChunkPayload]) -> None:
    if not chunks:
        return
    name = collection_name(tenant_id)
    if not client.collection_exists(name):
        create_tenant_collection(client, tenant_id)

    points = []
    for chunk in chunks:
        point_id = str(uuid5(NAMESPACE_URL, f"{chunk.document_id}:{chunk.chunk_index}"))
        points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    "dense": embed_dense(chunk.chunk_text),
                    "sparse": embed_sparse(chunk.chunk_text),
                },
                payload=chunk.to_qdrant_payload(),
            )
        )
    client.upsert(collection_name=name, points=points, wait=True)


def update_document_workflow_state(client: QdrantClient, tenant_id: str, document_id: str, state: str) -> None:
    """Update workflow metadata on every indexed chunk for a document."""
    name = collection_name(tenant_id)
    if not client.collection_exists(name):
        return
    client.set_payload(
        collection_name=name,
        payload={"workflow_state": state},
        points=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
            )
        ),
        wait=True,
    )