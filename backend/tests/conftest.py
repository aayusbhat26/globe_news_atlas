import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure backend directory is in python path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.config import settings  # noqa: E402
from app.middleware.rate_limit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Keep the in-memory limiter from leaking between tests."""
    limiter.reset()
    yield
    limiter.reset()


# The repository .env may point at a live TiDB database. Unit tests must be
# hermetic, so default to SQLite unless MySQL integration tests are opted in.
if os.getenv("AUTH_MYSQL_TESTS", "").strip().lower() not in {"1", "true", "yes"}:
    settings.auth_db_backend = "sqlite"
    settings.auth_test_db_name = None
    settings.auth_db_path = str(
        Path(tempfile.mkdtemp(prefix="gna-test-auth-")) / "auth.db"
    )
    settings.auth_secret = settings.auth_secret or "test-secret-for-globe-news-atlas"
    settings.environment = "development"
