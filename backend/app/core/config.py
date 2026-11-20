"""Environment-based configuration. No secrets have defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    env: str = field(default_factory=lambda: _env("APP_ENV", "development") or "development")
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "sqlite+aiosqlite:///./authentic_spark.db") or ""
    )
    # "firebase" verifies Firebase ID tokens; "dev" accepts `dev:<email>` bearer tokens (local/tests only).
    auth_mode: str = field(default_factory=lambda: _env("AUTH_MODE", "dev") or "dev")
    firebase_project_id: str | None = field(default_factory=lambda: _env("FIREBASE_PROJECT_ID"))
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS", "http://localhost:3000") or "")
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini")
    webhook_signing_secret: str | None = field(default_factory=lambda: _env("WEBHOOK_SIGNING_SECRET"))
    scheduler_token: str | None = field(default_factory=lambda: _env("SCHEDULER_TOKEN"))
    zerobounce_api_key: str | None = field(default_factory=lambda: _env("ZEROBOUNCE_API_KEY"))
    ngpvan_app_name: str | None = field(default_factory=lambda: _env("NGPVAN_APP_NAME"))
    ngpvan_api_key: str | None = field(default_factory=lambda: _env("NGPVAN_API_KEY"))
    scaletowin_api_key: str | None = field(default_factory=lambda: _env("SCALETOWIN_API_KEY"))
    asana_token: str | None = field(default_factory=lambda: _env("ASANA_ACCESS_TOKEN"))
    asana_webhook_secret: str | None = field(default_factory=lambda: _env("ASANA_WEBHOOK_SECRET"))
    slack_bot_token: str | None = field(default_factory=lambda: _env("SLACK_BOT_TOKEN"))
    qbo_client_id: str | None = field(default_factory=lambda: _env("QBO_CLIENT_ID"))
    qbo_client_secret: str | None = field(default_factory=lambda: _env("QBO_CLIENT_SECRET"))
    qbo_webhook_verifier: str | None = field(default_factory=lambda: _env("QBO_WEBHOOK_VERIFIER_TOKEN"))
    qbo_environment: str = field(default_factory=lambda: _env("QBO_ENVIRONMENT", "sandbox") or "sandbox")
    google_client_id: str | None = field(default_factory=lambda: _env("GOOGLE_OAUTH_CLIENT_ID"))
    google_client_secret: str | None = field(default_factory=lambda: _env("GOOGLE_OAUTH_CLIENT_SECRET"))
    google_ads_developer_token: str | None = field(default_factory=lambda: _env("GOOGLE_ADS_DEVELOPER_TOKEN"))
    mixpanel_token: str | None = field(default_factory=lambda: _env("MIXPANEL_TOKEN"))
    oauth_redirect_base: str = field(
        default_factory=lambda: _env("OAUTH_REDIRECT_BASE", "http://localhost:8080") or ""
    )
    rate_limit_per_minute: int = field(default_factory=lambda: int(_env("RATE_LIMIT_PER_MINUTE", "300") or 300))

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def get_settings() -> Settings:
    return Settings()
