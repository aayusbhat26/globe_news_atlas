"""Optional integration coverage for the TiDB/MySQL auth backend.

Skipped unless the local environment points AUTH_DB_BACKEND at MySQL and exposes
AUTH_TEST_DB_NAME. It never touches AUTH_DB_NAME.
"""
from __future__ import annotations

import uuid

import pymysql
import pytest

from app.auth.store import AuthStore
from app.config import settings

pytestmark = pytest.mark.skipif(
    (settings.auth_db_backend or "").strip().lower() not in {"mysql", "tidb"}
    or not settings.auth_test_db_name,
    reason="MySQL test database is not configured",
)

TABLES = (
    "reader_prefs",
    "watchlines",
    "auth_events",
    "recovery_codes",
    "login_challenges",
    "oauth_identities",
    "oauth_states",
    "auth_tokens",
    "sessions",
    "users",
)


def _admin_connection():
    return pymysql.connect(
        host=settings.auth_db_host,
        port=int(settings.auth_db_port),
        user=settings.auth_db_user,
        password=settings.auth_db_password,
        database=settings.auth_test_db_name,
        ssl_ca=settings.auth_db_ssl_ca,
        ssl_verify_cert=True,
        ssl_verify_identity=True,
        autocommit=True,
    )


def test_mysql_auth_store_round_trip(monkeypatch):
    test_db = settings.auth_test_db_name
    assert test_db and test_db != settings.auth_db_name, "refusing to test against the app database"
    admin = _admin_connection()
    with admin.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        for table in TABLES:
            cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
    admin.close()

    monkeypatch.setattr(settings, "auth_db_name", test_db)
    store = AuthStore()
    store.ensure_ready()

    email = f"mysql-test-{uuid.uuid4().hex[:10]}@example.com"
    user = store.create_user(email, "MySQL Test", "argon2-placeholder", email_verified=True)
    user_id = user["user_id"]
    assert store.get_user_by_email(email)["user_id"] == user_id

    token_hash = uuid.uuid4().hex * 2
    store.create_session(
        user_id,
        token_hash,
        "password",
        False,
        "127.0.0.1",
        "pytest",
        9_999_999_999,
        9_999_999_999,
    )
    session = store.get_session(token_hash)
    assert session and session["user_id"] == user_id

    status, entry = store.add_watchline(user_id, "place", "india", "India", 8)
    assert status == "created" and entry["key"] == "india"
    store.set_watchline_seen(user_id, 100)
    store.set_watchline_seen(user_id, 200)
    assert store.get_watchline_seen(user_id) == 200

    store.link_identity("google", "subject-1", user_id, email)
    store.link_identity("google", "subject-1", user_id, email)
    assert store.get_identity("google", "subject-1")["user_id"] == user_id

    store.record_event(user_id, "mysql_test", "127.0.0.1", "pytest", {"ok": True})
    assert store.list_events(user_id)[0]["event"] == "mysql_test"

    store.delete_user(user_id)
    assert store.get_user_by_id(user_id) is None
