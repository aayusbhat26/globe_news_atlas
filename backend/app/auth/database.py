"""Connection management for reader account storage.

SQLite remains the zero-setup local and test backend. MySQL/TiDB is used when
``AUTH_DB_BACKEND=mysql``; it adds TLS, a bounded connection pool and a small
reconnect layer because TiDB Cloud Starter can suspend idle instances.
"""
from __future__ import annotations

import base64
import queue
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings


class DatabaseIntegrityError(Exception):
    """Portable integrity error raised by non-SQLite backends."""


class DatabaseUnavailableError(RuntimeError):
    """Raised when the external account database cannot serve a request."""


class MySQLConnection:
    def __init__(self, raw: Any) -> None:
        self.raw = raw

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cursor = self.raw.cursor()
        try:
            cursor.execute(sql.replace("?", "%s"), params)
        except pymysql.err.IntegrityError as exc:
            raise DatabaseIntegrityError(str(exc)) from exc
        return cursor

    def executemany(self, sql: str, params: Sequence[Sequence[Any]]) -> Any:
        cursor = self.raw.cursor()
        try:
            cursor.executemany(sql.replace("?", "%s"), params)
        except pymysql.err.IntegrityError as exc:
            raise DatabaseIntegrityError(str(exc)) from exc
        return cursor


class MySQLPool:
    def __init__(self, size: int) -> None:
        self._size = max(1, int(size or 5))
        self._idle: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=self._size)
        self._created = 0
        self._lock = threading.Lock()

    def _new(self) -> Any:
        required = {
            "AUTH_DB_HOST": settings.auth_db_host,
            "AUTH_DB_NAME": settings.auth_db_name,
            "AUTH_DB_USER": settings.auth_db_user,
            "AUTH_DB_PASSWORD": settings.auth_db_password,
        }
        missing = [key for key, value in required.items() if not (value or "").strip()]
        if missing:
            raise DatabaseUnavailableError(
                "Missing TiDB settings: " + ", ".join(missing)
            )
        ca_path = (settings.auth_db_ssl_ca or "").strip()
        if not ca_path:
            pem = (settings.auth_db_ssl_ca_pem or "").strip().replace("\\n", "\n")
            encoded = (settings.auth_db_ssl_ca_pem_b64 or "").strip()
            if not pem and encoded:
                try:
                    pem = base64.b64decode(encoded).decode("utf-8")
                except Exception as exc:
                    raise DatabaseUnavailableError(
                        "AUTH_DB_SSL_CA_PEM_B64 is not valid base64"
                    ) from exc
            if pem:
                target = Path(settings.data_dir) / "auth" / "tidb-ca.pem"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(pem.strip() + "\n", encoding="utf-8")
                ca_path = str(target)
        if not ca_path or not Path(ca_path).is_file():
            raise DatabaseUnavailableError("AUTH_DB_SSL_CA is missing or unreadable")
        try:
            return pymysql.connect(
                host=settings.auth_db_host,
                port=max(1, int(settings.auth_db_port)),
                user=settings.auth_db_user,
                password=settings.auth_db_password,
                database=settings.auth_db_name,
                charset="utf8mb4",
                cursorclass=DictCursor,
                ssl_ca=ca_path,
                ssl_verify_cert=True,
                ssl_verify_identity=True,
                connect_timeout=12,
                read_timeout=20,
                write_timeout=20,
                autocommit=False,
            )
        except Exception as exc:
            raise DatabaseUnavailableError(
                f"Could not connect to the account database: {type(exc).__name__}"
            ) from exc

    def acquire(self) -> Any:
        for _ in range(2):
            try:
                connection = self._idle.get_nowait()
            except queue.Empty:
                with self._lock:
                    can_create = self._created < self._size
                    if can_create:
                        self._created += 1
                if can_create:
                    try:
                        return self._new()
                    except Exception:
                        with self._lock:
                            self._created -= 1
                        raise
                try:
                    connection = self._idle.get(timeout=15)
                except queue.Empty as exc:
                    raise DatabaseUnavailableError(
                        "Timed out waiting for an account database connection"
                    ) from exc
            try:
                connection.ping()
                return connection
            except Exception:
                self._discard(connection)
        raise DatabaseUnavailableError("Could not obtain a healthy account database connection")

    def release(self, connection: Any) -> None:
        try:
            connection.rollback()
        except Exception:
            self._discard(connection)
            return
        try:
            self._idle.put_nowait(connection)
        except queue.Full:
            self._discard(connection)

    def discard(self, connection: Any) -> None:
        self._discard(connection)

    def _discard(self, connection: Any) -> None:
        try:
            connection.close()
        except Exception:
            pass
        with self._lock:
            self._created = max(0, self._created - 1)


class MySQLBackend:
    def __init__(self) -> None:
        self._pool = MySQLPool(settings.auth_db_pool_size)

    @contextmanager
    def connection(self) -> Iterator[MySQLConnection]:
        raw = self._pool.acquire()
        wrapper = MySQLConnection(raw)
        try:
            yield wrapper
            raw.commit()
        except Exception:
            try:
                raw.rollback()
            except Exception:
                pass
            raise
        finally:
            self._pool.release(raw)

    def ensure_schema(self, statements: Sequence[str]) -> None:
        with self.connection() as conn:
            for statement in statements:
                conn.execute(statement)
