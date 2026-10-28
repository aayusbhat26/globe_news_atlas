import json
import os
from pathlib import Path
from typing import Annotated, List, Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode

ROOT_DIR = Path(__file__).resolve().parents[2]

_DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]


def _split_list(value: object) -> object:
    """Accept JSON arrays or comma-separated values for list settings."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in text.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """API settings. The backend only reads gold serving artifacts."""

    environment: str = "development"
    log_level: str = "INFO"

    data_dir: str = str(ROOT_DIR / "data")
    seeds_dir: str = str(ROOT_DIR / "seeds")

    snapshot_refresh_seconds: int = 60
    stream_poll_seconds: int = 10
    max_visible_arcs: int = 200

    # Hugging Face dataset repo used as the shared persistence layer.
    # When configured, a cold backend downloads gold/serving/*.json on startup.
    hf_token: Optional[str] = None
    hf_repo: Optional[str] = Field(default=None, validation_alias=AliasChoices("HF_DATASET_REPO", "HF_REPO"))
    hf_storage_type: str = "dataset"
    hf_pull_serving: bool = True
    hf_pull_interval_seconds: int = 120

    # Cross-origin browser clients must be listed explicitly. Same-origin
    # requests (the production SPA served by this API) never need CORS.
    allowed_origins: Annotated[List[str], NoDecode] = []
    # Host header allow-list for TrustedHostMiddleware. Render deployments
    # should set ALLOWED_HOSTS to the public service hostname.
    allowed_hosts: Annotated[List[str], NoDecode] = list(_DEFAULT_ALLOWED_HOSTS)
    # Only trust CF-Connecting-IP when the app is behind a proxy that sets it.
    # Render sets RENDER=true, which enables this automatically.
    trust_proxy_headers: bool = False
    # Maximum age of serving artifacts before /ready reports stale data.
    snapshot_max_age_seconds: int = 3 * 60 * 60

    # ── Reader accounts ──────────────────────────────────────────────
    # Everything below is server-side only. Secrets never reach the bundle.
    auth_secret: Optional[str] = None
    # sqlite (local/tests) or mysql (TiDB Cloud Starter or MySQL 8)
    auth_db_backend: str = "sqlite"
    auth_db_path: Optional[str] = None
    auth_db_host: Optional[str] = None
    auth_db_port: int = 4000
    auth_db_name: Optional[str] = None
    auth_db_user: Optional[str] = None
    auth_db_password: Optional[str] = None
    auth_db_ssl_ca: Optional[str] = None
    auth_db_ssl_ca_pem: Optional[str] = None
    auth_db_ssl_ca_pem_b64: Optional[str] = None
    auth_db_pool_size: int = 5
    auth_test_db_name: Optional[str] = None
    auth_min_password_length: int = 12
    auth_check_breached_passwords: bool = True
    # Argon2 is memory-hard; cap concurrent hash/verify operations so a burst
    # of logins cannot exhaust the instance.
    auth_hash_concurrency: int = 2
    auth_session_ttl_hours: int = 168
    auth_session_remember_ttl_hours: int = 720
    auth_absolute_session_days: int = 90
    auth_lockout_attempts: int = 8
    auth_cookie_secure: Optional[bool] = None
    auth_cookie_samesite: str = "lax"
    auth_cookie_domain: Optional[str] = None
    # Public URL of the React app, used in email links and OAuth redirects.
    app_base_url: Optional[str] = None
    # Public origin of this API, used to build the exact Google callback URI.
    public_base_url: Optional[str] = None

    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: Optional[str] = None
    google_oauth_timeout_seconds: int = 10

    # ── Transactional email ──────────────────────────────────────────
    # provider: auto | resend | smtp | dev
    email_provider: str = "auto"
    brevo_api_key: Optional[str] = None
    email_from: str = "Globe News Atlas <no-reply@globenewsatlas.local>"
    email_reply_to: Optional[str] = None
    resend_api_key: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_ca_file: Optional[str] = None
    email_timeout_seconds: int = 10

    model_config = {
        "env_file": (str(ROOT_DIR / ".env"), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("allowed_origins", "allowed_hosts", mode="before")
    @classmethod
    def _parse_list_settings(cls, value: object) -> object:
        return _split_list(value)

    @model_validator(mode="after")
    def _production_requirements(self) -> "Settings":
        """Fail fast on insecure or unusable production configuration."""
        if (self.environment or "").strip().lower() != "production":
            return self
        missing: List[str] = []
        secret = (self.auth_secret or "").strip()
        if len(secret) < 32:
            missing.append("AUTH_SECRET (at least 32 characters)")
        if not (self.app_base_url or "").strip():
            missing.append("APP_BASE_URL")
        if not (self.public_base_url or "").strip():
            missing.append("PUBLIC_BASE_URL")
        if (self.auth_db_backend or "sqlite").strip().lower() in {"mysql", "tidb"}:
            for field_name in (
                "auth_db_host",
                "auth_db_name",
                "auth_db_user",
                "auth_db_password",
            ):
                if not (getattr(self, field_name) or "").strip():
                    missing.append(field_name.upper())
        if missing:
            raise ValueError(
                "Production configuration is incomplete: " + ", ".join(missing)
            )
        return self

    @property
    def is_production(self) -> bool:
        return (self.environment or "").strip().lower() == "production"

    @property
    def resolved_allowed_hosts(self) -> List[str]:
        values = [item.strip() for item in (self.allowed_hosts or []) if item.strip()]
        render_host = (os.getenv("RENDER_EXTERNAL_HOSTNAME") or "").strip()
        if "://" in render_host:
            render_host = render_host.split("://", 1)[1]
        render_host = render_host.split("/", 1)[0]
        if render_host and render_host not in values:
            values.append(render_host)
        return values or list(_DEFAULT_ALLOWED_HOSTS)

    @property
    def google_login_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def email_delivery(self) -> str:
        if self.email_provider in {"resend", "smtp", "dev", "brevo"}:
            return self.email_provider
        if self.resend_api_key:
            return "resend"
        if self.brevo_api_key:
            return "brevo"
        if self.smtp_host:
            return "smtp"
        return "dev" if self.environment != "production" else "unconfigured"

    @property
    def secure_cookies(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.environment == "production"


settings = Settings()
