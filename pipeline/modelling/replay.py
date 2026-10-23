"""Compact replay archive built from the gold snapshot parts.

Every pipeline run already persists the full windowed snapshots. This module
turns that history into a bounded, globe-ready series so the API can serve an
Atlas Rewind and compute event momentum without reading Parquet at request time.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("pipeline.modelling.replay")

SOURCE_WINDOW = "24h"
HISTORY_DAYS = 30
MAX_FRAMES = 120
EVENTS_PER_FRAME = 50
ARCS_PER_FRAME = 18

_EVENT_FIELDS = (
    "id",
    "lat",
    "lng",
    "cat",
    "imp",
    "t",
    "at",
    "oc",
    "sp",
    "st",
    "sb",
    "ss",
    "cg",
    "cw",
    "loc",
    "gp",
    "src",
)
_ARC_FIELDS = (
    "id",
    "a",
    "b",
    "countries",
    "ty",
    "dir",
    "stg",
    "imp",
    "n",
    "a_lat",
    "a_lng",
    "b_lat",
    "b_lng",
)


def _compact_event(event: Dict[str, Any]) -> Dict[str, Any]:
    compact = {field: event.get(field) for field in _EVENT_FIELDS if event.get(field) is not None}
    compact["t"] = str(compact.get("t") or "")[:160]
    compact["loc"] = str(compact.get("loc") or "")[:120]
    compact["src"] = str(compact.get("src") or "")[:80]
    return compact


def _compact_arc(arc: Dict[str, Any]) -> Dict[str, Any]:
    compact = {field: arc.get(field) for field in _ARC_FIELDS if arc.get(field) is not None}
    compact["event_ids"] = list(arc.get("event_ids") or [])[:8]
    return compact


def _select_frames(frames: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if len(frames) <= limit:
        return frames
    if limit <= 1:
        return [frames[-1]]
    indexes = sorted({round(index * (len(frames) - 1) / (limit - 1)) for index in range(limit)})
    return [frames[index] for index in indexes]


class ReplayBuilder:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self.parts_root = self.data_dir / "gold" / "snapshots"

    def _parts(self, since: datetime) -> List[Path]:
        if not self.parts_root.exists():
            return []
        cutoff = since.date()
        parts: List[Path] = []
        for directory in sorted(self.parts_root.glob("dt=*")):
            try:
                partition = datetime.fromisoformat(directory.name.split("=", 1)[-1]).date()
            except ValueError:
                continue
            if partition < cutoff:
                continue
            parts.extend(sorted(directory.glob("part-*.parquet")))
        return parts

    def _read_frames(self, since: datetime) -> List[Dict[str, Any]]:
        frames: Dict[str, Dict[str, Any]] = {}
        for path in self._parts(since):
            try:
                frame = pd.read_parquet(
                    path, columns=["window", "ts", "payload", "_run_id"]
                )
            except Exception as exc:  # unreadable legacy parts must not break the run
                logger.warning("Skipping unreadable snapshot part %s: %s", path, exc)
                continue
            for row in frame.to_dict("records"):
                if str(row.get("window") or "") != SOURCE_WINDOW:
                    continue
                payload = row.get("payload")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        continue
                if not isinstance(payload, dict):
                    continue
                run_id = str(row.get("_run_id") or payload.get("run_id") or "")
                stamp = str(payload.get("ts") or row.get("ts") or "")
                if not run_id or not stamp:
                    continue
                events = payload.get("events") or []
                arcs = payload.get("arcs") or []
                frames[run_id] = {
                    "run_id": run_id,
                    "ts": stamp,
                    "counts": payload.get("n") or {},
                    "events": [
                        _compact_event(event)
                        for event in events[:EVENTS_PER_FRAME]
                        if isinstance(event, dict) and event.get("id")
                    ],
                    "arcs": [
                        _compact_arc(arc)
                        for arc in arcs[:ARCS_PER_FRAME]
                        if isinstance(arc, dict) and arc.get("id")
                    ],
                }
        return sorted(frames.values(), key=lambda item: item["ts"])

    def build(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        frames = self._read_frames(now - timedelta(days=HISTORY_DAYS))
        total = len(frames)
        frames = _select_frames(frames, MAX_FRAMES)
        payload = {
            "generated_at": now.isoformat(),
            "source_window": SOURCE_WINDOW,
            "history_days": HISTORY_DAYS,
            "available_runs": total,
            "frames": frames,
        }
        logger.info(
            "Replay archive: %d of %d snapshot runs kept (%s → %s)",
            len(frames),
            total,
            frames[0]["ts"] if frames else "none",
            frames[-1]["ts"] if frames else "none",
        )
        return payload
