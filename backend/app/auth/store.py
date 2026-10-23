"""Persistence for reader accounts, sessions and security events.

SQLite is the zero-setup local/test backend. When ``AUTH_DB_BACKEND=mysql`` the
same store uses a pooled TLS connection to TiDB Cloud Starter or MySQL 8.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from app.config import settings
from app.auth.database import MySQLBackend
from app.auth.security import now_ts

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    email_verified_at INTEGER,
    password_hash TEXT,
    display_name TEXT NOT NULL,
    locale TEXT NOT NULL DEFAULT 'en',
    totp_secret_enc TEXT,
    totp_pending_enc TEXT,
    totp_pending_created_at INTEGER,
    totp_enabled_at INTEGER,
    totp_last_step INTEGER,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER,
    last_login_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    auth_method TEXT NOT NULL,
    remember INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    user_agent TEXT,
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    absolute_expires_at INTEGER NOT NULL,
    revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id, expires_at);

CREATE TABLE IF NOT EXISTS auth_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);
CREATE INDEX IF NOT EXISTS auth_tokens_user_idx ON auth_tokens(user_id, purpose);

CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    nonce TEXT NOT NULL,
    next_path TEXT NOT NULL,
    link_user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER
);

CREATE TABLE IF NOT EXISTS oauth_identities (
    provider TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (provider, subject)
);
CREATE UNIQUE INDEX IF NOT EXISTS oauth_identity_user_idx
    ON oauth_identities(user_id, provider);

CREATE TABLE IF NOT EXISTS login_challenges (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    remember INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    user_agent TEXT,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS recovery_codes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    used_at INTEGER
);
CREATE INDEX IF NOT EXISTS recovery_codes_user_idx ON recovery_codes(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS recovery_codes_hash_idx ON recovery_codes(code_hash);

CREATE TABLE IF NOT EXISTS auth_events (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    event TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    metadata TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_events_user_idx ON auth_events(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS watchlines (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(user_id, kind, key)
);
CREATE INDEX IF NOT EXISTS watchlines_user_idx ON watchlines(user_id, created_at);

CREATE TABLE IF NOT EXISTS reader_prefs (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    watchline_seen_at INTEGER
);
"""

# MySQL/TiDB DDL is intentionally index-inline: MySQL has no CREATE INDEX IF
# NOT EXISTS. Foreign keys are omitted because TiDB deployments differ in
# enforcement; delete_user() cleans dependent rows explicitly.
_MYSQL_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS users (
        id VARCHAR(64) NOT NULL,
        email VARCHAR(255) NOT NULL,
        email_verified_at BIGINT NULL,
        password_hash TEXT NULL,
        display_name VARCHAR(80) NOT NULL,
        locale VARCHAR(16) NOT NULL DEFAULT 'en',
        totp_secret_enc TEXT NULL,
        totp_pending_enc TEXT NULL,
        totp_pending_created_at BIGINT NULL,
        totp_enabled_at BIGINT NULL,
        totp_last_step BIGINT NULL,
        failed_login_count INT NOT NULL DEFAULT 0,
        locked_until BIGINT NULL,
        last_login_at BIGINT NULL,
        created_at BIGINT NOT NULL,
        updated_at BIGINT NOT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY users_email_idx (email)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        token_hash VARCHAR(128) NOT NULL,
        auth_method VARCHAR(32) NOT NULL,
        remember TINYINT NOT NULL DEFAULT 0,
        ip VARCHAR(64) NULL,
        user_agent VARCHAR(400) NULL,
        created_at BIGINT NOT NULL,
        last_seen_at BIGINT NOT NULL,
        expires_at BIGINT NOT NULL,
        absolute_expires_at BIGINT NOT NULL,
        revoked_at BIGINT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY sessions_token_idx (token_hash),
        KEY sessions_user_idx (user_id, expires_at)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_tokens (
        id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        purpose VARCHAR(32) NOT NULL,
        token_hash VARCHAR(128) NOT NULL,
        created_at BIGINT NOT NULL,
        expires_at BIGINT NOT NULL,
        used_at BIGINT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY auth_tokens_hash_idx (token_hash),
        KEY auth_tokens_user_idx (user_id, purpose)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_states (
        state_hash VARCHAR(128) NOT NULL,
        code_verifier VARCHAR(255) NOT NULL,
        nonce VARCHAR(255) NOT NULL,
        next_path VARCHAR(500) NOT NULL,
        link_user_id VARCHAR(64) NULL,
        created_at BIGINT NOT NULL,
        expires_at BIGINT NOT NULL,
        used_at BIGINT NULL,
        PRIMARY KEY (state_hash),
        KEY oauth_states_user_idx (link_user_id)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_identities (
        provider VARCHAR(32) NOT NULL,
        subject VARCHAR(255) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        email VARCHAR(255) NULL,
        created_at BIGINT NOT NULL,
        PRIMARY KEY (provider, subject),
        UNIQUE KEY oauth_identity_user_idx (user_id, provider)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS login_challenges (
        token_hash VARCHAR(128) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        remember TINYINT NOT NULL DEFAULT 0,
        attempts INT NOT NULL DEFAULT 0,
        ip VARCHAR(64) NULL,
        user_agent VARCHAR(400) NULL,
        created_at BIGINT NOT NULL,
        expires_at BIGINT NOT NULL,
        PRIMARY KEY (token_hash)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS recovery_codes (
        id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        code_hash VARCHAR(128) NOT NULL,
        created_at BIGINT NOT NULL,
        used_at BIGINT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY recovery_codes_hash_idx (code_hash),
        KEY recovery_codes_user_idx (user_id)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_events (
        id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NULL,
        `event` VARCHAR(64) NOT NULL,
        ip VARCHAR(64) NULL,
        user_agent VARCHAR(400) NULL,
        metadata TEXT NULL,
        created_at BIGINT NOT NULL,
        PRIMARY KEY (id),
        KEY auth_events_user_idx (user_id, created_at)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS watchlines (
        id VARCHAR(64) NOT NULL,
        user_id VARCHAR(64) NOT NULL,
        kind VARCHAR(16) NOT NULL,
        `key` VARCHAR(120) NOT NULL,
        label VARCHAR(120) NOT NULL,
        created_at BIGINT NOT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY watchlines_user_key_idx (user_id, kind, `key`),
        KEY watchlines_user_idx (user_id, created_at)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS reader_prefs (
        user_id VARCHAR(64) NOT NULL,
        watchline_seen_at BIGINT NULL,
        PRIMARY KEY (user_id)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
)

_user_columns = """
    u.id AS user_id, u.email, u.email_verified_at, u.password_hash, u.display_name,
    u.locale, u.totp_secret_enc, u.totp_enabled_at, u.totp_last_step,
    u.failed_login_count, u.locked_until, u.last_login_at,
    u.created_at AS user_created_at, u.updated_at AS user_updated_at
"""


class AuthStore:
    def __init__(self) -> None:
        self._ready: set[str] = set()
        self._lock = threading.Lock()
        self._mysql: Optional[MySQLBackend] = None

    @property
    def path(self) -> Path:
        configured = (settings.auth_db_path or "").strip()
        if configured:
            return Path(configured)
        return Path(settings.data_dir) / "auth" / "auth.db"

    @property
    def is_mysql(self) -> bool:
        return (settings.auth_db_backend or "sqlite").strip().lower() in {"mysql", "tidb"}

    def _mysql_backend(self) -> MySQLBackend:
        if self._mysql is None:
            self._mysql = MySQLBackend()
        return self._mysql

    def ensure_ready(self) -> None:
        self._ensure_schema()

    def reset_runtime_state(self) -> None:
        """Test helper: forget schema markers and pooled connections."""
        with self._lock:
            self._ready.clear()
            self._mysql = None

    def _ensure_schema(self) -> None:
        if self.is_mysql:
            key = (
                f"mysql:{settings.auth_db_host}:{settings.auth_db_port}"
                f"/{settings.auth_db_name}/{settings.auth_db_user}"
            )
            if key in self._ready:
                return
            with self._lock:
                if key in self._ready:
                    return
                self._mysql_backend().ensure_schema(_MYSQL_TABLES)
                self._ready.add(key)
            return

        key = str(self.path.resolve())
        if key in self._ready:
            return
        with self._lock:
            if key in self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                conn.execute("PRAGMA user_version=1")
            self._ready.add(key)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        self._ensure_schema()
        if self.is_mysql:
            with self._mysql_backend().connection() as conn:
                yield conn
            return
        with self._connect() as conn:
            yield conn

    # ── users ────────────────────────────────────────────────────────

    def create_user(
        self,
        email: str,
        display_name: str,
        password_hash: Optional[str],
        email_verified: bool = False,
    ) -> Any:
        timestamp = now_ts()
        user_id = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    id, email, email_verified_at, password_hash, display_name,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email,
                    timestamp if email_verified else None,
                    password_hash,
                    display_name,
                    timestamp,
                    timestamp,
                ),
            )
            return conn.execute(
                f"SELECT {_user_columns} FROM users u WHERE u.id = ?", (user_id,)
            ).fetchone()

    def get_user_by_id(self, user_id: str) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                f"SELECT {_user_columns} FROM users u WHERE u.id = ?", (user_id,)
            ).fetchone()

    def get_user_by_email(self, email: str) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                f"SELECT {_user_columns} FROM users u WHERE u.email = ?", (email,)
            ).fetchone()

    def update_profile(self, user_id: str, display_name: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?",
                (display_name, now_ts(), user_id),
            )

    def mark_email_verified(self, user_id: str) -> None:
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?),
                    updated_at = ? WHERE id = ?
                """,
                (timestamp, timestamp, user_id),
            )

    def update_password(self, user_id: str, password_hash: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE users SET password_hash = ?, failed_login_count = 0,
                    locked_until = NULL, updated_at = ? WHERE id = ?
                """,
                (password_hash, now_ts(), user_id),
            )

    def record_login_failure(
        self, user_id: str, failed_count: int, locked_until: Optional[int]
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE users SET failed_login_count = ?, locked_until = ?,
                    updated_at = ? WHERE id = ?
                """,
                (failed_count, locked_until, now_ts(), user_id),
            )

    def record_login_success(self, user_id: str) -> None:
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE users SET failed_login_count = 0, locked_until = NULL,
                    last_login_at = ?, updated_at = ? WHERE id = ?
                """,
                (timestamp, timestamp, user_id),
            )

    def delete_user(self, user_id: str) -> None:
        # Child rows are removed explicitly so deletion works identically on
        # SQLite and TiDB, where foreign-key enforcement can differ.
        with self.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM oauth_states WHERE link_user_id = ?", (user_id,))
            conn.execute("DELETE FROM oauth_identities WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM login_challenges WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM watchlines WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM reader_prefs WHERE user_id = ?", (user_id,))
            conn.execute("UPDATE auth_events SET user_id = NULL WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # ── sessions ─────────────────────────────────────────────────────

    def create_session(
        self,
        user_id: str,
        token_hash: str,
        auth_method: str,
        remember: bool,
        ip: Optional[str],
        user_agent: Optional[str],
        expires_at: int,
        absolute_expires_at: int,
    ) -> str:
        session_id = uuid.uuid4().hex
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute(
                """
                DELETE FROM sessions
                WHERE revoked_at IS NOT NULL AND revoked_at < ?
                """,
                (timestamp - 60 * 60 * 24 * 30,),
            )
            conn.execute(
                """
                INSERT INTO sessions (
                    id, user_id, token_hash, auth_method, remember, ip, user_agent,
                    created_at, last_seen_at, expires_at, absolute_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    token_hash,
                    auth_method,
                    1 if remember else 0,
                    ip,
                    (user_agent or "")[:400] or None,
                    timestamp,
                    timestamp,
                    expires_at,
                    absolute_expires_at,
                ),
            )
        return session_id

    def get_session(self, token_hash: str) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                f"""
                SELECT s.id AS session_id, s.user_id, s.auth_method, s.remember,
                    s.ip, s.user_agent, s.created_at AS session_created_at,
                    s.last_seen_at, s.expires_at, s.absolute_expires_at,
                    s.revoked_at, {_user_columns}
                FROM sessions s JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ? AND s.revoked_at IS NULL
                """,
                (token_hash,),
            ).fetchone()

    def touch_session(
        self, session_id: str, last_seen_at: int, expires_at: int
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
                (last_seen_at, expires_at, session_id),
            )

    def revoke_session(self, session_id: str, user_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE sessions SET revoked_at = ?
                WHERE id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (now_ts(), session_id, user_id),
            )
            return cursor.rowcount > 0

    def revoke_all_sessions(
        self, user_id: str, except_session_id: Optional[str] = None
    ) -> int:
        timestamp = now_ts()
        with self.connection() as conn:
            if except_session_id:
                cursor = conn.execute(
                    """
                    UPDATE sessions SET revoked_at = ?
                    WHERE user_id = ? AND id != ? AND revoked_at IS NULL
                    """,
                    (timestamp, user_id, except_session_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE sessions SET revoked_at = ?
                    WHERE user_id = ? AND revoked_at IS NULL
                    """,
                    (timestamp, user_id),
                )
            return cursor.rowcount

    def list_sessions(self, user_id: str) -> list[Any]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT id, auth_method, remember, ip, user_agent, created_at,
                    last_seen_at, expires_at, absolute_expires_at
                FROM sessions
                WHERE user_id = ? AND revoked_at IS NULL
                ORDER BY last_seen_at DESC
                """,
                (user_id,),
            ).fetchall()

    # ── one-time email tokens ────────────────────────────────────────

    def create_auth_token(
        self, user_id: str, purpose: str, token_hash: str, expires_at: int
    ) -> None:
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE auth_tokens SET used_at = ?
                WHERE user_id = ? AND purpose = ? AND used_at IS NULL
                """,
                (timestamp, user_id, purpose),
            )
            conn.execute(
                """
                INSERT INTO auth_tokens (id, user_id, purpose, token_hash, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uuid.uuid4().hex, user_id, purpose, token_hash, timestamp, expires_at),
            )
            conn.execute(
                "DELETE FROM auth_tokens WHERE created_at < ?",
                (timestamp - 60 * 60 * 24 * 30,),
            )

    def get_auth_token(
        self, token_hash: str, purpose: str
    ) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                f"""
                SELECT t.id, t.user_id, t.purpose, t.expires_at, t.used_at,
                    {_user_columns}
                FROM auth_tokens t JOIN users u ON u.id = t.user_id
                WHERE t.token_hash = ? AND t.purpose = ?
                """,
                (token_hash, purpose),
            ).fetchone()

    def consume_auth_token(self, token_id: str, user_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE auth_tokens SET used_at = ?
                WHERE id = ? AND user_id = ? AND used_at IS NULL
                """,
                (now_ts(), token_id, user_id),
            )
            return cursor.rowcount > 0

    def last_auth_token_at(self, user_id: str, purpose: str) -> Optional[int]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT created_at FROM auth_tokens
                WHERE user_id = ? AND purpose = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, purpose),
            ).fetchone()
            return int(row["created_at"]) if row else None

    # ── OAuth state and identities ───────────────────────────────────

    def create_oauth_state(
        self,
        state_hash: str,
        code_verifier: str,
        nonce: str,
        next_path: str,
        expires_at: int,
        link_user_id: Optional[str] = None,
    ) -> None:
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (timestamp - 3600,))
            conn.execute(
                """
                INSERT INTO oauth_states (
                    state_hash, code_verifier, nonce, next_path, link_user_id,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state_hash,
                    code_verifier,
                    nonce,
                    next_path,
                    link_user_id,
                    timestamp,
                    expires_at,
                ),
            )

    def get_oauth_state(self, state_hash: str) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM oauth_states WHERE state_hash = ?",
                (state_hash,),
            ).fetchone()

    def consume_oauth_state(self, state_hash: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE oauth_states SET used_at = ?
                WHERE state_hash = ? AND used_at IS NULL
                """,
                (now_ts(), state_hash),
            )
            return cursor.rowcount > 0

    def get_identity(self, provider: str, subject: str) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT provider, subject, user_id, email, created_at
                FROM oauth_identities WHERE provider = ? AND subject = ?
                """,
                (provider, subject),
            ).fetchone()

    def get_identity_for_user(
        self, user_id: str, provider: str
    ) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT provider, subject, user_id, email, created_at
                FROM oauth_identities WHERE user_id = ? AND provider = ?
                """,
                (user_id, provider),
            ).fetchone()

    def link_identity(
        self, provider: str, subject: str, user_id: str, email: Optional[str]
    ) -> None:
        sql = (
            """
            INSERT INTO oauth_identities (provider, subject, user_id, email, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE user_id = VALUES(user_id), email = VALUES(email)
            """
            if self.is_mysql
            else """
            INSERT INTO oauth_identities (provider, subject, user_id, email, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, subject) DO UPDATE SET user_id = excluded.user_id,
                email = excluded.email
            """
        )
        with self.connection() as conn:
            conn.execute(sql, (provider, subject, user_id, email, now_ts()))

    def unlink_identity(self, provider: str, user_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM oauth_identities WHERE provider = ? AND user_id = ?",
                (provider, user_id),
            )
            return cursor.rowcount > 0

    # ── login challenges (second factor) ─────────────────────────────

    def create_login_challenge(
        self,
        token_hash: str,
        user_id: str,
        remember: bool,
        ip: Optional[str],
        user_agent: Optional[str],
        expires_at: int,
    ) -> None:
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute("DELETE FROM login_challenges WHERE expires_at < ?", (timestamp,))
            conn.execute(
                """
                INSERT INTO login_challenges (
                    token_hash, user_id, remember, ip, user_agent, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token_hash,
                    user_id,
                    1 if remember else 0,
                    ip,
                    (user_agent or "")[:400] or None,
                    timestamp,
                    expires_at,
                ),
            )

    def get_login_challenge(self, token_hash: str) -> Optional[Any]:
        with self.connection() as conn:
            return conn.execute(
                f"""
                SELECT c.token_hash, c.user_id, c.remember, c.attempts, c.ip,
                    c.user_agent, c.created_at, c.expires_at, {_user_columns}
                FROM login_challenges c JOIN users u ON u.id = c.user_id
                WHERE c.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()

    def increment_challenge_attempts(self, token_hash: str) -> int:
        with self.connection() as conn:
            conn.execute(
                "UPDATE login_challenges SET attempts = attempts + 1 WHERE token_hash = ?",
                (token_hash,),
            )
            row = conn.execute(
                "SELECT attempts FROM login_challenges WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            return int(row["attempts"]) if row else 0

    def delete_login_challenge(self, token_hash: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM login_challenges WHERE token_hash = ?", (token_hash,)
            )

    # ── TOTP and recovery codes ──────────────────────────────────────

    def set_totp_pending(self, user_id: str, encrypted_secret: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE users SET totp_pending_enc = ?, totp_pending_created_at = ?,
                    updated_at = ? WHERE id = ?
                """,
                (encrypted_secret, now_ts(), now_ts(), user_id),
            )

    def get_totp_pending(self, user_id: str) -> Optional[tuple[str, int]]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT totp_pending_enc, totp_pending_created_at FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
        if not row or not row["totp_pending_enc"]:
            return None
        return row["totp_pending_enc"], int(row["totp_pending_created_at"] or 0)

    def enable_totp(self, user_id: str) -> None:
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE users SET totp_secret_enc = totp_pending_enc,
                    totp_pending_enc = NULL, totp_pending_created_at = NULL,
                    totp_enabled_at = ?, totp_last_step = NULL, updated_at = ?
                WHERE id = ? AND totp_pending_enc IS NOT NULL
                """,
                (timestamp, timestamp, user_id),
            )

    def disable_totp(self, user_id: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE users SET totp_secret_enc = NULL, totp_pending_enc = NULL,
                    totp_pending_created_at = NULL, totp_enabled_at = NULL,
                    totp_last_step = NULL, updated_at = ? WHERE id = ?
                """,
                (now_ts(), user_id),
            )
            conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))

    def set_totp_step(self, user_id: str, step: int) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE users SET totp_last_step = ? WHERE id = ?", (step, user_id)
            )

    def replace_recovery_codes(self, user_id: str, hashes: list[str]) -> None:
        timestamp = now_ts()
        with self.connection() as conn:
            conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
            conn.executemany(
                """
                INSERT INTO recovery_codes (id, user_id, code_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                [(uuid.uuid4().hex, user_id, item, timestamp) for item in hashes],
            )

    def list_recovery_codes(self, user_id: str) -> list[Any]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT id, code_hash, created_at, used_at FROM recovery_codes
                WHERE user_id = ? ORDER BY created_at
                """,
                (user_id,),
            ).fetchall()

    def mark_recovery_code_used(self, code_id: str, user_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE recovery_codes SET used_at = ?
                WHERE id = ? AND user_id = ? AND used_at IS NULL
                """,
                (now_ts(), code_id, user_id),
            )
            return cursor.rowcount > 0

    # ── watchlines ───────────────────────────────────────────────────

    def list_watchlines(self, user_id: str) -> list[Any]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT id, kind, `key`, label, created_at FROM watchlines
                WHERE user_id = ? ORDER BY created_at, id
                """,
                (user_id,),
            ).fetchall()

    def add_watchline(
        self, user_id: str, kind: str, key: str, label: str, limit: int
    ) -> tuple[str, Optional[Any]]:
        """Returns (status, row) where status is created, exists or limit."""
        with self.connection() as conn:
            existing = conn.execute(
                """
                SELECT id, kind, `key`, label, created_at FROM watchlines
                WHERE user_id = ? AND kind = ? AND `key` = ?
                """,
                (user_id, kind, key),
            ).fetchone()
            if existing:
                return "exists", existing
            total = conn.execute(
                "SELECT COUNT(*) AS total FROM watchlines WHERE user_id = ?", (user_id,)
            ).fetchone()
            if int(total["total"] if total else 0) >= limit:
                return "limit", None
            entry_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO watchlines (id, user_id, kind, `key`, label, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (entry_id, user_id, kind, key, label, now_ts()),
            )
            row = conn.execute(
                "SELECT id, kind, `key`, label, created_at FROM watchlines WHERE id = ?",
                (entry_id,),
            ).fetchone()
            return "created", row

    def remove_watchline(self, user_id: str, entry_id: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM watchlines WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            )
            return cursor.rowcount > 0

    def get_watchline_seen(self, user_id: str) -> Optional[int]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT watchline_seen_at FROM reader_prefs WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return int(row["watchline_seen_at"]) if row and row["watchline_seen_at"] else None

    def set_watchline_seen(self, user_id: str, timestamp: int) -> None:
        sql = (
            """
            INSERT INTO reader_prefs (user_id, watchline_seen_at) VALUES (?, ?)
            ON DUPLICATE KEY UPDATE watchline_seen_at = VALUES(watchline_seen_at)
            """
            if self.is_mysql
            else """
            INSERT INTO reader_prefs (user_id, watchline_seen_at) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET watchline_seen_at = excluded.watchline_seen_at
            """
        )
        with self.connection() as conn:
            conn.execute(sql, (user_id, timestamp))

    # ── audit events ─────────────────────────────────────────────────

    def record_event(
        self,
        user_id: Optional[str],
        event: str,
        ip: Optional[str],
        user_agent: Optional[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO auth_events (id, user_id, `event`, ip, user_agent, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    user_id,
                    event,
                    ip,
                    (user_agent or "")[:400] or None,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now_ts(),
                ),
            )

    def list_events(self, user_id: str, limit: int = 12) -> list[Any]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT `event`, ip, user_agent, metadata, created_at
                FROM auth_events WHERE user_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (user_id, max(1, min(limit, 50))),
            ).fetchall()

    def count_recovery_codes(self, user_id: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total FROM recovery_codes
                WHERE user_id = ? AND used_at IS NULL
                """,
                (user_id,),
            ).fetchone()
            return int(row["total"]) if row else 0


auth_store = AuthStore()
