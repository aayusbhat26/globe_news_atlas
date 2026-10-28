"""Builds compact window snapshots served by the API."""
import gzip
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pipeline.config import WINDOWS

logger = logging.getLogger("pipeline.modelling.snapshot_generator")


def _parse_stamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def window_span(
    events: Iterable[Dict[str, Any]],
    now: datetime,
    window: str,
) -> Dict[str, Any]:
    """Actual available history for a window, independent of the top-N cap."""
    minutes = WINDOWS.get(window)
    if minutes is None:
        return {}
    requested_from = now - timedelta(minutes=minutes)
    stamps = [
        stamp
        for stamp in (_parse_stamp(event.get("at")) for event in events)
        if stamp is not None
    ]
    if not stamps:
        return {
            "requested_hours": round(minutes / 60, 2),
            "span_hours": 0.0,
            "available_from": None,
            "available_to": None,
            "requested_from": requested_from.isoformat(),
            "span_complete": False,
        }
    oldest, newest = min(stamps), max(stamps)
    # Allow an hour of clock/schedule slack at the far edge.
    complete = oldest <= requested_from + timedelta(hours=1)
    return {
        "requested_hours": round(minutes / 60, 2),
        "span_hours": round((newest - oldest).total_seconds() / 3600.0, 2),
        "available_from": oldest.isoformat(),
        "available_to": newest.isoformat(),
        "requested_from": requested_from.isoformat(),
        "span_complete": complete,
    }


def select_window_events(
    events: List[Dict[str, Any]],
    now: datetime,
    window: str,
    cap: int,
    required_ids: Optional[Iterable[str]] = None,
    coded_label: str = "GDELT event record",
) -> tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """Select a bounded top-N window while guaranteeing monotonic windows.

    Every id selected for a narrower window is carried into the wider one, so
    a 7d snapshot cannot drop an event shown in 24h (and 30d cannot drop 7d).
    """
    minutes = WINDOWS.get(window)
    if minutes is None:
        return [], 0, {}
    cutoff = now - timedelta(minutes=minutes)
    candidates: List[Dict[str, Any]] = []
    for event in events:
        if event.get("lat") is None or event.get("lng") is None:
            continue
        if str(event.get("src") or "") == coded_label:
            continue
        stamp = _parse_stamp(event.get("at"))
        if stamp and stamp >= cutoff:
            candidates.append(event)
    candidates.sort(key=lambda event: (event.get("imp", 0.0), event.get("at") or ""), reverse=True)

    by_id = {str(event.get("id")): event for event in candidates if event.get("id")}
    required = [str(event_id) for event_id in (required_ids or []) if str(event_id) in by_id]
    limit = max(int(cap or 0), len(required))
    selected: List[Dict[str, Any]] = []
    seen: set = set()
    for event_id in required:
        event = by_id[event_id]
        selected.append(event)
        seen.add(event_id)
    for event in candidates:
        if len(selected) >= limit:
            break
        event_id = str(event.get("id"))
        if event_id in seen:
            continue
        selected.append(event)
        seen.add(event_id)
    selected.sort(key=lambda event: (event.get("imp", 0.0), event.get("at") or ""), reverse=True)

    meta = window_span(candidates, now, window)
    meta["shown"] = len(selected)
    meta["total"] = len(candidates)
    meta["top_n"] = True
    meta["capped"] = len(selected) < len(candidates)
    return selected, len(candidates), meta


class SnapshotGenerator:
    MAX_GZIPPED_BYTES = 300 * 1024

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        events: List[Dict[str, Any]],
        arcs: List[Dict[str, Any]],
        window_name: str = "24h",
        generated_at: Optional[str] = None,
        total_events: Optional[int] = None,
        window_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        unique_events = {event["id"]: event for event in events if event.get("id") and event.get("lat") is not None}
        ordered = sorted(
            unique_events.values(),
            key=lambda event: (event.get("imp", 0.0), event.get("at") or ""),
            reverse=True,
        )
        event_ids = {event["id"] for event in ordered}
        relevant_arcs = [arc for arc in arcs if set(arc.get("event_ids", [])) & event_ids]
        relevant_arcs.sort(key=lambda arc: (arc.get("n", 0), arc.get("imp", 0)), reverse=True)

        available = max(len(ordered), int(total_events or 0))
        meta = dict(window_meta or {})
        if not meta and events:
            now = _parse_stamp(generated_at) or datetime.now(timezone.utc)
            meta = window_span(events, now, window_name)
        # Without window metadata, preserve the historical contract that the
        # caller-supplied total is a complete window total.
        span_complete = bool(meta.get("span_complete", not meta))
        counts: Dict[str, Any] = {
            "e": len(ordered),
            "a": len(relevant_arcs),
            # n.total is a window total only when the available history actually
            # covers the requested window. Otherwise it is the top-N shown and
            # n.available carries the true (but incomplete) pool size.
            "total": available if span_complete else len(ordered),
            "capped": span_complete and len(ordered) < available,
            "available": available,
            "available_capped": len(ordered) < available,
            # n.e is the top-N shown.
            "shown": len(ordered),
            "top_n": True,
            "window": window_name,
            "requested_hours": meta.get("requested_hours"),
            "span_hours": meta.get("span_hours"),
            "available_from": meta.get("available_from"),
            "available_to": meta.get("available_to"),
            "requested_from": meta.get("requested_from"),
            "span_complete": span_complete,
            "total_scope": "window" if span_complete else "available",
            "window_total": available if span_complete else None,
        }
        if not span_complete:
            counts["total_note"] = (
                f"Available history starts {meta.get('available_from') or 'unknown'}; "
                f"this is not a complete {window_name} total."
            )
        snapshot = {
            "ts": generated_at or datetime.now(timezone.utc).isoformat(),
            "w": window_name,
            "n": counts,
            "events": ordered,
            "arcs": relevant_arcs,
        }
        snapshot = self._enforce_size_limit(snapshot)
        self._write(snapshot, window_name)
        return snapshot

    def _enforce_size_limit(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        while True:
            raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(gzip.compress(raw)) <= self.MAX_GZIPPED_BYTES:
                break
            if snapshot["events"] and len(snapshot["events"]) > 20:
                snapshot["events"] = snapshot["events"][:-max(1, len(snapshot["events"]) // 10)]
            elif snapshot["arcs"]:
                snapshot["arcs"] = snapshot["arcs"][:-max(1, len(snapshot["arcs"]) // 5)]
            else:
                break
            total = int(snapshot["n"].get("total") or len(snapshot["events"]))
            counts = dict(snapshot["n"])
            counts.update(
                {
                    "e": len(snapshot["events"]),
                    "a": len(snapshot["arcs"]),
                    "total": max(total, len(snapshot["events"])),
                    "capped": bool(counts.get("span_complete", True))
                    and len(snapshot["events"]) < max(total, len(snapshot["events"])),
                    "available": max(
                        int(counts.get("available") or total),
                        len(snapshot["events"]),
                    ),
                    "available_capped": len(snapshot["events"]) < int(counts.get("available") or total),
                    "shown": len(snapshot["events"]),
                    "top_n": True,
                }
            )
            snapshot["n"] = counts
        return snapshot

    def _write(self, snapshot: Dict[str, Any], window_name: str) -> None:
        raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        json_path = self.output_dir / f"world_{window_name}.json"
        gz_path = self.output_dir / f"world_{window_name}.json.gz"
        tmp_path = json_path.with_suffix(".json.tmp")
        tmp_path.write_text(raw, encoding="utf-8")
        os.replace(tmp_path, json_path)
        gz_tmp = gz_path.with_suffix(".gz.tmp")
        gz_tmp.write_bytes(gzip.compress(raw.encode("utf-8")))
        os.replace(gz_tmp, gz_path)

    @staticmethod
    def read_existing(output_dir: Path, window_name: str) -> Optional[Dict[str, Any]]:
        path = Path(output_dir) / f"world_{window_name}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
