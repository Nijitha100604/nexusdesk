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

    # Data stores
    mongodb_uri: str = "mongodb://localhost:27017/nexusdesk"
    chroma_path: str = "./chroma_data"

    # Security
    jwt_secret: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
