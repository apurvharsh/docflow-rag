"""Env-driven settings, loaded once and imported everywhere else."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_path: str = "qdrant_data"
    database_path: str = "docflow.db"
    uploads_path: str = "uploads"

    gemini_api_key: str | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_generation_model: str = "gemini-3.6-flash"

    dense_embedding_model: str = "BAAI/bge-base-en-v1.5"
    dense_embedding_dim: int = 768

    sparse_embedding_model: str = "prithivida/Splade_PP_en_v1"

    reranker_model: str = "BAAI/bge-reranker-base"

    top_k_fetch: int = 40
    top_k_final: int = 6

    dev_tenant_id: str = "local"
    dev_user_id: str = "local-user"
    dev_org_admin: bool = True
    dev_sensitivity_clearance: int = 1
    auth_secret: str = "change-this-secret"
    auth_username: str = "admin"
    auth_password: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"


settings = Settings()
