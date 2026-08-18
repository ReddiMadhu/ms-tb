"""
mstr-tableau-migrator — Core configuration via pydantic-settings.

Loads from .env file or environment variables.
Ref: spec/architecture.md §3.3, spec/database.md §1.1
"""

from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide configuration. All values configurable via .env or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MSTR Connection ──────────────────────────────────────────────
    mstr_base_url: str = "https://demo.microstrategy.com/MicroStrategyLibrary"
    mstr_username: str = ""
    mstr_password: str = ""
    mstr_project_id: str = ""

    # ── Tableau Server Connection ────────────────────────────────────
    tableau_server_url: str = ""
    tableau_site_id: str = ""
    tableau_token_name: str = ""
    tableau_token_value: str = ""

    # ── Warehouse Connection (ADR-022 — warehouse-direct extraction) ─
    warehouse_type: str = "sqlserver"
    warehouse_host: str = ""
    warehouse_port: int = 1433
    warehouse_database: str = ""
    warehouse_username: str = ""
    warehouse_password: str = ""

    # ── LLM Configuration ────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = "gpt-4o-2"
    azure_openai_api_version: str = "2024-02-15-preview"
    use_llm_cache: bool = True
    llm_cache_dir: str = "./artifacts/llm_cache"

    # ── Application Settings ─────────────────────────────────────────
    database_url: str = "sqlite:///./artifacts/migrations.db"
    artifacts_dir: str = "./artifacts"
    template_version: str = "2024.2"
    log_level: str = "INFO"

    # ── Validation Thresholds (ADR-018 / ADR-025) ────────────────────
    numeric_threshold: float = 0.98
    kpi_tolerance: float = 0.001
    security_confidence_required: float = 1.0
    structural_confidence_required: float = 0.99
    visual_confidence_required: float = 0.80

    # ── Session Management (ADR-016) ─────────────────────────────────
    mstr_token_renewal_margin_s: int = 60
    mstr_page_size: int = 10000

    # ── Audit Configuration (ADR-020) ────────────────────────────────
    audit_batch_size: int = 100
    audit_flush_interval_s: float = 5.0

    @field_validator("artifacts_dir", "llm_cache_dir")
    @classmethod
    def ensure_dir_exists(cls, v: str) -> str:
        Path(v).mkdir(parents=True, exist_ok=True)
        return v

    @property
    def db_path(self) -> Path:
        """Extract the filesystem path from the SQLite URL."""
        url = self.database_url
        if url.startswith("sqlite:///"):
            return Path(url.replace("sqlite:///", ""))
        return Path("./artifacts/migrations.db")


# Singleton instance — import this everywhere
settings = Settings()
