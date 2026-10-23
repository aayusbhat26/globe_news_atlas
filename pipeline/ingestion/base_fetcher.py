import time
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger("pipeline.ingestion.base")


class BaseFetcher(ABC):
    """
    Abstract base fetcher implementing circuit breaker and retry policies.
    """
    def __init__(self, name: str, max_retries: int = 3, circuit_break_seconds: int = 900):
        self.name = name
        self.max_retries = max_retries
        self.circuit_break_seconds = circuit_break_seconds
        self.consecutive_failures = 0
        self.circuit_opened_at: Optional[float] = None

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

    @abstractmethod
    def fetch(self) -> List[Dict[str, Any]]:
        """Fetch raw items and return as a list of raw dict payloads."""
        pass
