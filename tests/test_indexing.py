from tempfile import TemporaryDirectory

from qdrant_client import QdrantClient

from app.ingestion.indexing import index_chunks
from app.models.schema import ChunkPayload, UserContext
from app.retrieval.access_filter import build_access_filter
from app.retrieval.hybrid_search import hybrid_search


def test_chunks_are_indexed_and_retrievable(monkeypatch):
    monkeypatch.setattr("app.ingestion.indexing.embed_dense", lambda text: [1.0] * 768)
    chunks = [
        ChunkPayload(
            document_id="doc-1",
            project_id="project-1",
            stage="Design",
            doc_type="PRD",
            section_title="Overview",
            chunk_text="The service uses Gemini retrieval.",
        )
    ]
    user = UserContext(user_id="user-1", tenant_id="tenant-1", is_org_admin=True)

    with TemporaryDirectory() as path:
        client = QdrantClient(path=path)
        index_chunks(client, user.tenant_id, chunks)
        hits = hybrid_search(
            client,
            user.tenant_id,
            "Gemini retrieval",
            [1.0] * 768,
            __import__("app.retrieval.embeddings", fromlist=["embed_sparse"]).embed_sparse("Gemini retrieval"),
            build_access_filter(user),
        )
        client.close()

    assert len(hits) == 1
    assert hits[0]["payload"]["document_id"] == "doc-1"