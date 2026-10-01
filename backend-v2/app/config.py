"""Environment-based configuration. Every value has a safe local default."""

from functools import lru_cache
from typing import Annotated, Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv(value):
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "CourtLens Backend"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "sqlite:///./courtlens.db"
    auto_migrate: bool = True

    api_v1_prefix: str = "/api/v1"
    cors_allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173", "http://127.0.0.1:5173",
    ]

    storage_dir: str = "./storage"
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_upload_extensions: Annotated[list[str], NoDecode] = [
        ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".txt", ".docx",
    ]
    allowed_upload_mime_types: Annotated[list[str], NoDecode] = [
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/tiff",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]

    # Optional API-key gate. Empty/None means open (development trust boundary).
    api_key: Optional[SecretStr] = None

    agent_timeout_seconds: float = 30.0
    agent_max_attempts: int = 2
    agent_retry_delay_seconds: float = 0.5
    max_run_retries: int = 3
    auto_reanalyze_on_new_document: bool = False

    document_agent_class: Optional[str] = None
    conflict_agent_class: Optional[str] = None
    reasoning_agent_class: Optional[str] = None
    ocr_agent_class: Optional[str] = None
    evidence_agent_class: Optional[str] = None
    rule_agent_class: Optional[str] = None
    summary_agent_class: Optional[str] = None
    enable_demo_agents: bool = False
    sync_analysis_execution: bool = True
    background_worker_threads: int = 2
    api_key_permissions: Annotated[list[str], NoDecode] = []

    ai_provider: Optional[str] = None
    ai_provider_api_key: Optional[SecretStr] = None
    ai_provider_base_url: Optional[str] = None

    @field_validator("allowed_upload_extensions", "allowed_upload_mime_types",
                     "api_key_permissions", "cors_allowed_origins", mode="before")
    @classmethod
    def _csv(cls, value):
        return _split_csv(value)

    @field_validator("allowed_upload_extensions")
    @classmethod
    def _normalise_extensions(cls, value: list[str]) -> list[str]:
        return [v.lower() if v.startswith(".") else f".{v.lower()}" for v in value]

    @field_validator(
        "api_key", "ai_provider_api_key", "document_agent_class", "conflict_agent_class",
        "reasoning_agent_class", "ai_provider", "ai_provider_base_url", mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def api_key_value(self) -> Optional[str]:
        return self.api_key.get_secret_value() if self.api_key else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
