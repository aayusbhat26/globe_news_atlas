"""Builds compact window snapshots served by the API."""
import gzip
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pipeline.modelling.snapshot_generator")


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
        snapshot = {
            "ts": generated_at or datetime.now(timezone.utc).isoformat(),
            "w": window_name,
            "n": {
                "e": len(ordered),
                "a": len(relevant_arcs),
                "total": available,
                "capped": len(ordered) < available,
            },
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
            snapshot["n"] = {
                "e": len(snapshot["events"]),
                "a": len(snapshot["arcs"]),
                "total": max(total, len(snapshot["events"])),
                "capped": len(snapshot["events"]) < max(total, len(snapshot["events"])),
            }
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
