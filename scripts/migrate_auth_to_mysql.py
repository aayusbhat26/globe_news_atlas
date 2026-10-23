"""Copy local SQLite reader accounts into the configured MySQL/TiDB database.

Safe for repeated runs: inserts use INSERT IGNORE and never delete target data.
Sessions and one-time tokens are copied only because AUTH_SECRET is expected to
remain stable; otherwise users simply sign in again.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.auth.database import MySQLBackend  # noqa: E402
from app.auth.store import _MYSQL_TABLES  # noqa: E402
from app.config import settings  # noqa: E402

TABLES = [
    (
        "users",
        "id, email, email_verified_at, password_hash, display_name, locale, "
        "totp_secret_enc, totp_pending_enc, totp_pending_created_at, totp_enabled_at, "
        "totp_last_step, failed_login_count, locked_until, last_login_at, created_at, updated_at",
    ),
    (
        "sessions",
        "id, user_id, token_hash, auth_method, remember, ip, user_agent, created_at, "
        "last_seen_at, expires_at, absolute_expires_at, revoked_at",
    ),
    ("auth_tokens", "id, user_id, purpose, token_hash, created_at, expires_at, used_at"),
    (
        "oauth_states",
        "state_hash, code_verifier, nonce, next_path, link_user_id, created_at, expires_at, used_at",
    ),
    ("oauth_identities", "provider, subject, user_id, email, created_at"),
    (
        "login_challenges",
        "token_hash, user_id, remember, attempts, ip, user_agent, created_at, expires_at",
    ),
    ("recovery_codes", "id, user_id, code_hash, created_at, used_at"),
    ("auth_events", "id, user_id, `event`, ip, user_agent, metadata, created_at"),
    ("watchlines", "id, user_id, kind, `key`, label, created_at"),
    ("reader_prefs", "user_id, watchline_seen_at"),
]


def source_path() -> Path:
    configured = (settings.auth_db_path or "").strip()
    return Path(configured) if configured else Path(settings.data_dir) / "auth" / "auth.db"


def main() -> int:
    if (settings.auth_db_backend or "").strip().lower() not in {"mysql", "tidb"}:
        print("AUTH_DB_BACKEND must be mysql for this migration.")
        return 2
    source = source_path()
    if not source.is_file():
        print(f"SQLite source not found: {source}")
        return 2

    sqlite_conn = sqlite3.connect(str(source))
    sqlite_conn.row_factory = sqlite3.Row
    backend = MySQLBackend()
    backend.ensure_schema(_MYSQL_TABLES)

    existing = {
        row[0]
        for row in sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    moved = {}
    with backend.connection() as target:
        for table, columns in TABLES:
            if table not in existing:
                moved[table] = 0
                continue
            rows = sqlite_conn.execute(f"SELECT {columns} FROM {table}").fetchall()
            if not rows:
                moved[table] = 0
                continue
            column_count = len(columns.split(","))
            placeholders = ", ".join("?" for _ in range(column_count))
            target.executemany(
                f"INSERT IGNORE INTO {table} ({columns}) VALUES ({placeholders})",
                [tuple(row) for row in rows],
            )
            moved[table] = len(rows)

    sqlite_conn.close()
    for table, count in moved.items():
        print(f"{table}: {count} source rows")
    print("Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
