from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    provider: Literal["deepseek", "fake"] = Field("deepseek", validation_alias="STUDYAGENT_PROVIDER")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    database_url: str = "postgresql://studyagent:studyagent_local@127.0.0.1:55432/studyagent"
    ollama_url: str = "http://127.0.0.1:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768
    search_provider: Literal["arxiv", "disabled"] = "arxiv"
    model_timeout: float = 90
    context_token_budget: int = 7000
    max_session_steps: int = 12
    upload_max_bytes: int = 20 * 1024 * 1024
    user_id: str = "local-demo"
    runtime_dir: Path = ROOT / "runtime"
