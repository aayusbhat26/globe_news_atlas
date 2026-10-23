import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import settings

logger = logging.getLogger("app.services.feedback")

_lock = threading.Lock()


class FeedbackService:
    """Appends user-submitted correction reports to a local JSONL file."""

    @property
    def path(self) -> Path:
        return Path(settings.data_dir) / "feedback" / "reports.jsonl"

    def record(self, payload: Dict[str, Any]) -> str:
        report_id = uuid.uuid4().hex
        record = {
            **payload,
            "id": report_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("Recorded feedback %s for event %s", report_id, payload.get("event_id"))
        return report_id


feedback_service = FeedbackService()
