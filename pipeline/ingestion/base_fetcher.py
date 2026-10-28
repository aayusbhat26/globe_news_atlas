import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger("pipeline.ingestion.base")

# Health states used by the manifest. "empty" is not a failure: a healthy
# optional source may legitimately have nothing to return.
FETCH_STATUSES = {"ok", "empty", "skipped", "failed", "partial"}


class BaseFetcher(ABC):
    """
    Abstract base fetcher implementing circuit breaker, retry policies and
    explicit per-run source health (ok/empty/skipped/partial/failed).
    """
    def __init__(self, name: str, max_retries: int = 3, circuit_break_seconds: int = 900):
        self.name = name
        self.max_retries = max_retries
        self.circuit_break_seconds = circuit_break_seconds
        self.consecutive_failures = 0
        self.circuit_opened_at: Optional[float] = None
        self.status = "unknown"
        self.error = ""
        self.skipped_reason = ""
        self.feed_errors: Dict[str, str] = {}

    def begin_fetch(self) -> None:
        self.status = "running"
        self.error = ""
        self.skipped_reason = ""
        self.feed_errors = {}

    def is_circuit_open(self) -> bool:
        if self.circuit_opened_at is None:
            return False
        if time.time() - self.circuit_opened_at > self.circuit_break_seconds:
            # Half-open: try again
            self.circuit_opened_at = None
            self.consecutive_failures = 0
            logger.info(f"Circuit breaker reset for {self.name}")
            return False
        return True

    def record_success(self):
        self.consecutive_failures = 0
        self.circuit_opened_at = None

    def record_failure(self):
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_retries:
            self.circuit_opened_at = time.time()
            logger.warning(
                f"Circuit breaker OPEN for {self.name} after {self.consecutive_failures} failures. "
                f"Pausing for {self.circuit_break_seconds}s."
            )

    def finish_fetch(
        self,
        records: List[Dict[str, Any]],
        *,
        status: Optional[str] = None,
        error: str = "",
        skipped_reason: str = "",
        feed_errors: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Record source health and return the fetched records.

        Zero records default to ``empty``, never ``failed``. Callers may pass
        an explicit status when a genuine upstream failure occurred.
        """
        if feed_errors:
            self.feed_errors = dict(feed_errors)
        self.error = error
        self.skipped_reason = skipped_reason
        if status is None:
            status = "empty" if not records else "ok"
        if status not in FETCH_STATUSES:
            status = "empty" if not records else "ok"
        self.status = status
        if status == "failed":
            self.record_failure()
        elif status == "skipped":
            self.record_success()
        elif records and status in {"ok", "partial"}:
            self.record_success()
        return records

    def health(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "failed": self.status == "failed",
            "empty": self.status == "empty",
            "skipped": self.status == "skipped",
            "partial": self.status == "partial",
            "error": self.error or None,
            "skipped_reason": self.skipped_reason or None,
            "per_feed_errors": dict(self.feed_errors),
        }

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch raw items and return as a list of raw dict payloads."""
        pass
