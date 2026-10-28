import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.auth.store import auth_store
from app.config import settings

logger = logging.getLogger("app.services.feedback")

_lock = threading.Lock()

MAX_EVENT_ID = 200
MAX_CATEGORY = 32
MAX_DETAILS = 4000


class FeedbackService:
    """Persist correction reports in the account database.

    The auth database (TiDB on Render, which has no persistent disk) is the
    primary store. The legacy JSONL file remains as a best-effort fallback when
    the database is unavailable. Only reporter-supplied fields are stored.
    """

    @property
    def path(self) -> Path:
        return Path(settings.data_dir) / "feedback" / "reports.jsonl"

    def _append_file(self, record: Dict[str, Any]) -> None:
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def record(self, payload: Dict[str, Any]) -> str:
        report_id = uuid.uuid4().hex
        event_id = (str(payload.get("event_id") or "").strip() or None)
        if event_id:
            event_id = event_id[:MAX_EVENT_ID]
        category = str(payload.get("category") or "").strip()[:MAX_CATEGORY]
        details = str(payload.get("details") or "")[:MAX_DETAILS]
        record = {
            "id": report_id,
            "event_id": event_id,
            "category": category,
            "details": details,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            auth_store.save_feedback(report_id, event_id, category, details)
            logger.info(
                "Recorded feedback %s for event %s", report_id, event_id
            )
            return report_id
        except Exception as exc:
            logger.warning(
                "Account database unavailable for feedback; using file fallback: %s",
                type(exc).__name__,
            )
        self._append_file(record)
        logger.info(
            "Recorded feedback %s for event %s (file fallback)",
            report_id,
            event_id,
        )
        return report_id


feedback_service = FeedbackService()
