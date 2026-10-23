import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("pipeline.dead_letter")


class DeadLetterHandler:
    def __init__(self, storage_dir: Optional[Path] = None):
        if storage_dir is None:
            self.storage_dir = Path(__file__).resolve().parent.parent.parent / "data" / "dead_letter"
        else:
            self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.storage_dir / "failed_tasks.jsonl"

    def record_failure(
        self,
        source: str,
        step: str,
        payload: Dict[str, Any],
        error_message: str,
        traceback_str: Optional[str] = None,
    ):
        entry = {
            "source": source,
            "failed_step": step,
            "error_message": error_message,
            "error_traceback": traceback_str,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "resolved": False,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        logger.warning(f"Recorded dead-letter item from step '{step}': {error_message}")


dead_letter_handler = DeadLetterHandler()
