from app import database


def test_database_keeps_multiple_documents_in_one_project(monkeypatch, tmp_path):
    monkeypatch.setattr(database.settings, "database_path", str(tmp_path / "test.db"))
    database.initialize_database()
    common = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "project_name": "Project One",
        "stage": "Design",
        "doc_type": "Notes",
        "sensitivity_level": 1,
    }
    database.record_document(document_id="doc-1", filename="one.txt", stored_path="one.txt", chunk_count=2, **common)
    database.record_document(document_id="doc-2", filename="two.pdf", stored_path="two.pdf", chunk_count=3, **common)

    projects = database.list_projects("tenant-1")
    documents = database.list_documents("tenant-1", "project-1")

    assert projects == [{"project_id": "project-1", "project_name": "Project One", "document_count": 2}]
    assert [document["filename"] for document in documents] == ["two.pdf", "one.txt"]


def test_record_document_is_idempotent_for_vector_backfill(monkeypatch, tmp_path):
    monkeypatch.setattr(database.settings, "database_path", str(tmp_path / "test.db"))
    database.initialize_database()
    document = {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "project_name": "Project One",
        "document_id": "doc-1",
        "filename": "one.txt",
        "stored_path": "one.txt",
        "stage": "Design",
        "doc_type": "Notes",
        "sensitivity_level": 1,
        "chunk_count": 2,
    }

    database.record_document(**document)
    database.record_document(**document)

    documents = database.list_documents("tenant-1", "project-1")
    assert len(documents) == 1
    assert documents[0]["document_id"] == "doc-1"


def test_database_list_all_documents_across_projects(monkeypatch, tmp_path):
    monkeypatch.setattr(database.settings, "database_path", str(tmp_path / "test.db"))
    database.initialize_database()
    database.record_document(
        tenant_id="tenant-1",
        project_id="proj-a",
        project_name="Alpha",
        document_id="doc-1",
        filename="alpha_prd.md",
        stored_path="alpha_prd.md",
        stage="Requirements",
        doc_type="PRD",
        sensitivity_level=1,
        chunk_count=5,
    )
    database.record_document(
        tenant_id="tenant-1",
        project_id="proj-b",
        project_name="Beta",
        document_id="doc-2",
        filename="beta_arch.pdf",
        stored_path="beta_arch.pdf",
        stage="Architecture",
        doc_type="Architecture Document",
        sensitivity_level=2,
        chunk_count=8,
    )

    all_docs = database.list_all_documents("tenant-1")
    assert len(all_docs) == 2
    filenames = {d["filename"] for d in all_docs}
    assert filenames == {"alpha_prd.md", "beta_arch.pdf"}
    project_names = {d["project_name"] for d in all_docs}
    assert project_names == {"Alpha", "Beta"}

