"""Application settings and configuration using Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global TARS application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TARS_",
        extra="ignore",
        case_sensitive=False,
    )

    # Application general settings
    app_name: str = Field(default="TARS", description="Application name")
    environment: Literal["development", "test", "production"] = Field(
        default="development", description="Execution environment"
    )
    debug: bool = Field(default=False, description="Debug mode flag")

    # Storage settings
    storage_dir: Path = Field(
        default=Path("./storage"),
        description="Root directory for multi-tenant file storage",
    )

    # Static files settings
    static_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "static",
        description="Root directory for static assets and PWA client",
    )

    # Database settings
    database_url: str = Field(
        default="postgresql+asyncpg://tarsuser:tarspassword@localhost:5432/tars",
        description="Async SQLAlchemy database URL (postgresql+asyncpg)",
    )
    db_echo: bool = Field(default=False, description="Echo SQL queries in logs")
    db_pool_size: int = Field(
        default=20, description="SQLAlchemy connection pool size"
    )
    db_max_overflow: int = Field(
        default=10, description="SQLAlchemy max pool overflow"
    )
    db_pool_timeout: float = Field(
        default=30.0, description="SQLAlchemy pool timeout in seconds"
    )
    db_pool_recycle: int = Field(
        default=1800, description="SQLAlchemy connection recycle in seconds"
    )
    db_pool_pre_ping: bool = Field(
        default=True, description="Enable connection health pre-ping"
    )

    # CORS Settings (SEC-01)
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
        ],
        description="Allowed CORS origin domains (explicit whitelist, no wildcard with credentials)",
    )

    # JWT Authentication settings
    jwt_secret_key: str = Field(
        default="tars-insecure-dev-secret-key-32-chars-minimum!!",
        description="Secret key for signing JWT tokens",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_access_token_expire_minutes: int = Field(
        default=60 * 24 * 7,  # 7 days
        description="JWT access token lifetime in minutes",
    )

    # TARS Persona default parameters
    default_humor_level: float = Field(
        default=0.90, ge=0.0, le=1.0, description="Default humor level (0.0 to 1.0)"
    )
    default_honesty_level: float = Field(
        default=0.95, ge=0.0, le=1.0, description="Default honesty level (0.0 to 1.0)"
    )
    default_mode: Literal["companion", "work"] = Field(
        default="companion", description="Default TARS operating mode"
    )

    # External LLM / SLM Endpoints
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model_name: str = Field(
        default="gemini-2.0-flash", description="Google Gemini model identifier"
    )
    llamacpp_base_url: str = Field(
        default="http://localhost:8080/v1", description="Local llama.cpp OpenAI-compatible base URL"
    )
    llamacpp_model_name: str = Field(
        default="default", description="Model name or alias for local llama.cpp server"
    )
    llamacpp_timeout_ms: int = Field(
        default=3000,
        ge=100,
        le=60000,
        description="Timeout in ms for local SLM streaming/generation",
    )

    # Dynamic Slicer Settings
    slicer_default_token_budget: int = Field(
        default=1500, ge=100, le=32000, description="Default max token budget for dynamic slicing"
    )

    # Google Workspace Settings
    google_mock_mode: bool = Field(
        default=True,
        description="Enable deterministic offline mock mode for Google Workspace APIs",
    )
    google_client_id: str = Field(default="", description="Google OAuth2 Client ID")
    google_client_secret: str = Field(default="", description="Google OAuth2 Client Secret")
    google_refresh_token: str = Field(default="", description="Google OAuth2 Refresh Token")
    google_calendar_id: str = Field(
        default="primary", description="Target Google Calendar ID for calendar tools"
    )

    # Model Context Protocol (MCP) Settings
    mcp_servers: list[dict[str, Any]] = Field(
        default_factory=list, description="Configured MCP server definitions"
    )
    mcp_client_timeout: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
        description="Default timeout in seconds for MCP client calls",
    )

    # LangGraph ReAct Tool Execution Settings
    max_tool_iterations: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum iterations in LangGraph ReAct loop",
    )
    cag_cache_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        description="TTL in seconds for static CAG context cache",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached singleton instance of Settings."""
    return Settings()
