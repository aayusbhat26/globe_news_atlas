import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("pipeline.analytics.quality")

MAX_AGE_HOURS = {"1h": 3, "24h": 30, "7d": 8 * 24, "30d": 32 * 24}


class DataQualityChecker:
    def __init__(self, snapshots_dir: Path):
        self.snapshots_dir = Path(snapshots_dir)

    def run_checks(self, window: str = "24h") -> Dict[str, Any]:
        snapshot_file = self.snapshots_dir / f"world_{window}.json"
        if not snapshot_file.exists():
            return {"passed": False, "error": "Snapshot file not found", "window": window}

        try:
            data = json.loads(snapshot_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"passed": False, "error": f"Unreadable snapshot: {exc}", "window": window}

        events = data.get("events", [])
        arcs = data.get("arcs", [])
        if not events:
            return {"passed": False, "error": "Zero events in snapshot", "window": window}

        invalid_coords = 0
        for event in events:
            try:
                lat, lng = float(event.get("lat")), float(event.get("lng"))
            except (TypeError, ValueError):
                invalid_coords += 1
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                invalid_coords += 1
        duplicate_ids = len(events) - len({event.get("id") for event in events})
        missing_summary = sum(1 for event in events if not (event.get("sum") or "").strip())
        single_source = sum(1 for event in events if event.get("ss"))
        gap_events = sum(1 for event in events if event.get("cg"))

        stale = False
        generated = data.get("ts")
        age_hours: Optional[float] = None
        try:
            timestamp = datetime.fromisoformat((generated or "").replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600
            stale = age_hours > MAX_AGE_HOURS.get(window, 48)
        except (TypeError, ValueError):
            stale = True

        warnings = []
        if invalid_coords:
            warnings.append(f"{invalid_coords} events have invalid coordinates")
        if duplicate_ids:
            warnings.append(f"{duplicate_ids} duplicate event ids")
        if missing_summary:
            warnings.append(f"{missing_summary} events have no summary")
        if stale:
            warnings.append("Snapshot is older than the expected refresh interval")
        if single_source / len(events) > 0.75:
            warnings.append("More than 75% of events rely on a single outlet")

        report = {
            "window": window,
            "passed": not warnings,
            "total_events": len(events),
            "total_arcs": len(arcs),
            "single_source_ratio": round(single_source / len(events), 2),
            "coverage_gap_count": gap_events,
            "invalid_coordinates": invalid_coords,
            "duplicate_ids": duplicate_ids,
            "missing_summary": missing_summary,
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "categories": sorted({event.get("cat", "unknown") for event in events}),
            "warnings": warnings,
            "timestamp": generated,
        }
        logger.info("Data quality (%s): %s", window, report)
        return report

    def check_all(self) -> Dict[str, Dict[str, Any]]:
        return {window: self.run_checks(window) for window in MAX_AGE_HOURS}


if __name__ == "__main__":
    snapshots_path = Path(__file__).resolve().parent.parent.parent / "data" / "gold" / "serving"
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(DataQualityChecker(snapshots_path).check_all(), indent=2))
