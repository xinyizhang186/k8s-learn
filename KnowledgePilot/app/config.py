from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "KnowledgePilot"
    database_url: str = "sqlite:///./data/knowledgepilot.db"
    redis_url: str = ""
    openalex_email: str = ""
    request_timeout: float = 20.0
    default_top_k: int = 8
    max_react_steps: int = 5
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_base_url: str = "http://127.0.0.1:8000"
    model_name: str = "rule-based-local"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    use_ollama: bool = True
    ollama_timeout: float = 120.0

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KP_", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
