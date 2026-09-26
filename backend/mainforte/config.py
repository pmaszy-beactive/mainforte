from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # .env.local (gitignored) overrides .env so local dev never touches the deployed database.
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field("dev", alias="APP_ENV")
    app_url: str = Field("http://localhost:5173", alias="APP_URL")
    frontend_url: str = Field("http://localhost:5173", alias="FRONTEND_URL")
    api_url: str = Field("http://localhost:8000", alias="API_URL")
    port: int = Field(8000, alias="PORT")

    secret_key: str = Field("dev-secret", alias="SECRET_KEY")
    auth_secret: str | None = Field(None, alias="AUTH_SECRET")
    state_secret: str | None = Field(None, alias="STATE_SECRET")
    support_users: str = Field(
        "paul@beactive.ai,alice@beactive.ai,kainat@beactive.ai", alias="SUPPORT_USERS"
    )

    database_url: str = Field("postgresql://mainforte:mainforte@localhost:5439/mainforte", alias="DATABASE_URL")
    redis_url: str = Field("redis://localhost:6390/0", alias="REDIS_URL")
    celery_broker_url: str = Field("amqp://mainforte:mainforte@localhost:5679/mainforte", alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(None, alias="CELERY_RESULT_BACKEND")

    sendgrid_api_key: str | None = Field(None, alias="SENDGRID_API_KEY")
    mail_default_sender: str = Field("no-reply@mainforte.ai", alias="MAIL_DEFAULT_SENDER")

    google_client_id: str | None = Field(None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(None, alias="GOOGLE_CLIENT_SECRET")

    stripe_secret_key: str | None = Field(None, alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: str | None = Field(None, alias="VITE_PUBLIC_STRIPE_PUBLISHABLE_KEY")

    s3_endpoint: str | None = Field(None, alias="S3_ENDPOINT")
    s3_api_key: str | None = Field(None, alias="S3_API_KEY")
    s3_secret_key: str | None = Field(None, alias="S3_SECRET_KEY")

    ai_proxy_base_url: str | None = Field(None, alias="AI_PROXY_BASE_URL")
    ai_proxy_admin_secret: str | None = Field(None, alias="AI_PROXY_ADMIN_SECRET")

    meeting_bot_base_url: str | None = Field(None, alias="MEETING_BOT_BASE_URL")
    meeting_bot_api_key: str | None = Field(None, alias="MEETING_BOT_API_KEY")

    jenkins_host: str | None = Field(None, alias="JENKINS_HOST")
    jenkins_port: int | None = Field(None, alias="JENKINS_PORT")

    session_ttl_days: int = 30
    impersonation_ttl_hours: int = 8
    event_stream_maxlen: int = 20_000

    # Sandboxed tool execution (P2 phase 3). sandbox_uid/gid must match Dockerfile.worker's
    # throwaway `sandbox` user; on hosts without `runuser` (local macOS dev) sandboxed tools
    # simply aren't runnable — they only work inside the actual worker container.
    sandbox_uid: int = Field(10100, alias="SANDBOX_UID")
    sandbox_gid: int = Field(10100, alias="SANDBOX_GID")
    sandbox_work_root: str = Field("/work", alias="SANDBOX_WORK_ROOT")
    sandbox_timeout_seconds: int = Field(60, alias="SANDBOX_TIMEOUT_SECONDS")

    @property
    def jwt_secret(self) -> str:
        return self.auth_secret or self.secret_key

    @property
    def superuser_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.support_users.split(",") if e.strip()}

    @property
    def is_prod(self) -> bool:
        return self.app_env in {"prod", "production"}

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
