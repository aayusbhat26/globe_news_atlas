from pathlib import Path
from typing import List, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).resolve().parents[2]


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

    allowed_origins: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://globenewsatlas.vercel.app",
    ]

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
