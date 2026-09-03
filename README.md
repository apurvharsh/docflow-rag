# DocFlow AI — RAG Module (Phase 2)

Hybrid dense+sparse retrieval with ABAC-filtered access control, built for
Qdrant collection-per-tenant isolation.

## Folder structure

```
docflow-rag/
├── .vscode/
│   ├── settings.json       # Python interpreter, formatting, test discovery
│   └── launch.json         # Debug configs for API + standalone scripts
├── app/
│   ├── config.py           # Env-driven settings (Qdrant host, model names, etc.)
│   ├── models/
│   │   └── schema.py       # ChunkPayload, UserContext, SensitivityLevel
│   ├── ingestion/
│   │   ├── collection_setup.py  # create_tenant_collection()
│   │   └── chunking.py           # structure-aware chunking + contextual headers
│   ├── retrieval/
│   │   ├── access_filter.py      # build_access_filter() — single ABAC source of truth
│   │   ├── embeddings.py         # dense + sparse embedding calls (stubs to wire up)
│   │   └── hybrid_search.py      # hybrid_search() — RRF fusion + rerank
│   └── api/
│       └── search.py             # FastAPI route wiring it all together
├── tests/
│   ├── test_access_filter.py
│   └── test_hybrid_search.py
├── requirements.txt
├── .env.example
└── .gitignore
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # fill in QDRANT_URL, embedding model, etc.
```

## Running tests

```bash
pytest tests/ -v
```

## Deploying on Render

This repository includes a Render Blueprint in `render.yaml`. Push the
repository to GitHub, create a new Blueprint on Render, and select the
repository. Render will install the dependencies, start FastAPI on its
assigned port, and use `/health` for service checks.

Set these secret environment variables in the Render dashboard when prompted:

- `GEMINI_API_KEY`
- `QDRANT_URL` and `QDRANT_API_KEY` when using a managed Qdrant cluster
- `AUTH_PASSWORD`

For Google sign-in, create a Google OAuth Web application and add these
variables too:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI` set to `https://<your-render-host>/auth/google/callback`

Register that exact callback URL in Google Cloud Console. Google sign-in is
available to new and existing users; password login remains available for
existing local accounts. The current development identity mapping applies the
configured tenant and permissions after Google verification. Connect it to a
user directory and identity-provider claims before using it for multi-user
corporate authorization.

The Blueprint mounts `/var/data` so SQLite, local Qdrant data, and uploads
survive service restarts. A managed Qdrant cluster is recommended for teams
and production scale. The current local authentication implementation is
appropriate for a controlled demo; replace `get_current_user()` with your
identity provider before exposing the service to a corporate network.

## Uploading documents

Start the API and open `http://127.0.0.1:8000/docs`. Use `POST /upload/batch`
to upload one or many `.txt`, `.md`, `.json`, `.pdf`, `.doc`, `.docx`, `.ppt`,
or `.pptx` files
into the same project. Provide the shared project, stage,
document type, and optional comma-separated team visibility fields in the
multipart form.

Uploads are stored under `uploads/<tenant_id>/`, chunked, embedded with Gemini,
and indexed into local Qdrant storage under `qdrant_data/`. Use `POST /ask` in
Swagger or the dashboard to retrieve authorized chunks and generate a grounded
Gemini answer. Set `GEMINI_API_KEY` in `.env` before uploading.

The current identity is a local development admin. Replace `get_current_user()`
in `app/api/search.py` with your authentication provider before exposing the
API outside your machine.

## Personal projects and notes

Any authenticated member can open **Project Spaces** and create multiple
personal projects. The creator automatically receives Member access and can
upload documents to each project. Organization admins can assign users to
multiple projects through **Access Control**.

The **Personal Notes** view stores private todos, meeting notes, and follow-up
items. Notes can remain personal or be associated with one of the user's
authorized projects. Notes are stored in SQLite and are visible only to their
owner.

## Where each finalized decision from the project doc lives

| Decision | File |
|---|---|
| Collection-per-tenant isolation | `app/ingestion/collection_setup.py` |
| Compound filter at query time, never post-filtered | `app/retrieval/access_filter.py` |
| One centralized `build_access_filter()` used by every retrieval path | `app/retrieval/access_filter.py` |
| Org-admin cross-project bypass | `app/retrieval/access_filter.py` |
| Same tagging (tenant/project/stage/team/sensitivity) across all 3 storage layers | `app/models/schema.py` |

## Next steps (not yet implemented — stubs marked with `NotImplementedError`)

- `app/retrieval/embeddings.py`: wire in actual Nomic/BGE dense model + BM25/SPLADE sparse model
- `app/retrieval/hybrid_search.py::_rerank`: wire in cross-encoder (bge-reranker or Cohere rerank)
- `app/api/search.py`: wire in your FastAPI auth dependency to populate `UserContext`
