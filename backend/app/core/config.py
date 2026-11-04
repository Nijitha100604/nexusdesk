from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]  # repository root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_env: str = "development"

    # LLM providers
    llm_provider: str = "groq"  # groq | gemini | ollama
    groq_api_key: str = ""
    gemini_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # ServiceNow (mock mode needs no instance)
    servicenow_mode: str = "mock"  # mock | live
    sn_instance: str = ""
    sn_user: str = ""
    sn_password: str = ""
    sn_kb_sys_id: str = ""
    sn_config_path: str = ""
    sn_timeout: float = 15.0
    sn_max_retries: int = 3

    # Data stores
    mongodb_uri: str = "mongodb://localhost:27017/nexusdesk"
    chroma_path: str = "./chroma_data"

    # Security
    jwt_secret: str = "change-me"

    llm_model: str = ""

    # RAG
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ".cache/embeddings"
    rag_collection: str = "nexusdesk_knowledge"
    rag_top_k: int = 5
    rag_min_similarity: float = 0.45
    rag_rerank: bool = False

    @property
    def chroma_dir(self) -> Path:
        return self._resolve(self.chroma_path)

    @property
    def embedding_cache(self) -> Path:
        return self._resolve(self.embedding_cache_dir)

    @staticmethod
    def _resolve(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
