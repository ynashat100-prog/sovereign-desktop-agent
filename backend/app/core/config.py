"""Runtime configuration. Secrets are read only from environment variables or local settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_host: str = "127.0.0.1"
    agent_port: int = 8765
    agent_data_dir: Path = Path("agent-data")
    agent_demo_mode: bool = False

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    moondream_model: str = "moondream"

    nvidia_api_key: str | None = None
    nvidia_model: str = "meta/llama-3.1-70b-instruct"
    mistral_api_key: str | None = None
    mistral_model: str = "mistral-small-latest"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-8b-instant"

    allow_clipboard_context: bool = False
    trace_retention_days: int = 7

    @property
    def memory_path(self) -> Path:
        return self.agent_data_dir / "memory"


settings = Settings()
