from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_assignment=True,
    )

    app_name: str = "GoMate"
    database_path: Path = Path("data/gomate.db")
    token_ttl_seconds: int = Field(default=86400, ge=60)
    remember_token_ttl_seconds: int = Field(default=2592000, ge=60, le=7776000)
    auth_cookie_secure: bool = False
    task_execution_mode: Literal["inline", "queue"] = "inline"
    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_port: int = Field(default=5672, ge=1, le=65535)
    rabbitmq_user: str = "gomate"
    rabbitmq_password: SecretStr = SecretStr("")
    rabbitmq_vhost: str = "/"
    rabbitmq_queue: str = Field(default="gomate.runs.v1", pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    worker_concurrency: int = Field(default=2, ge=1, le=4)
    worker_stale_seconds: int = Field(default=30, ge=15, le=120)
    login_max_attempts: int = Field(default=5, ge=1)
    login_window_seconds: int = Field(default=300, ge=1)
    run_timeout_seconds: int = Field(default=240, gt=0)
    max_active_runs_per_user: int = Field(default=2, ge=1)
    max_tool_calls_per_run: int = Field(default=32, ge=0)
    max_external_requests_per_run: int = Field(default=48, ge=0)
    max_llm_calls_per_run: int = Field(default=16, ge=0)
    tool_timeout_seconds: float = Field(default=10, gt=0)
    max_parallel_tools_per_run: int = Field(default=4, ge=1)
    llm_provider: Literal["deepseek"] = "deepseek"
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_thinking: Literal["disabled", "enabled"] = "disabled"
    llm_timeout_seconds: float = Field(default=30, gt=0)
    chat_history_messages: int = Field(default=20, ge=1, le=100)
    chat_history_chars: int = Field(default=40000, ge=16000, le=160000)
    chat_max_output_tokens: int = Field(default=4096, ge=128, le=8192)
    map_provider: Literal["amap"] = "amap"
    amap_web_service_key: SecretStr = SecretStr("")
    amap_js_api_key: str = ""
    amap_js_security_code: SecretStr = SecretStr("")
    default_city: str = ""
    map_timeout_seconds: float = Field(default=10, gt=0, le=30)
    amap_min_interval_seconds: float = Field(default=1.1, ge=0, le=5)
    transit_walk_fallback_meters: int = Field(default=2000, ge=0, le=5000)
    max_review_rounds: int = Field(default=2, ge=0, le=2)
    tavily_api_key: SecretStr = SecretStr("")
    web_search_timeout_seconds: float = Field(default=12, gt=0, le=30)
