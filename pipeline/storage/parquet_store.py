"""Local Parquet lake with Hive-style date partitions.

Layout:
    data/<layer>/<table>/dt=YYYY-MM-DD/part-<run_id>.parquet

Nested values are stored as JSON strings so the physical schema stays stable
across runs while still being queryable from DuckDB/pandas after decoding.
"""
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pandas as pd

logger = logging.getLogger("pipeline.storage.parquet")

LAYERS = ("bronze", "silver", "gold")

JSON_COLUMNS: Dict[str, set] = {
    "bronze/raw_articles": {"source_metadata", "raw_payload"},
    "bronze/raw_social": {"metadata"},
    "silver/articles": {"entities", "countries", "social", "source_metadata"},
    "gold/events": {"spectrum", "sp", "countries", "entities", "source_ids"},
    "gold/event_details": {
        "timeline",
        "coverage",
        "sources",
        "corrections",
        "related_event_ids",
        "related_relation_ids",
        "countries",
        "spectrum",
    },
    "gold/arcs": {"countries", "event_ids"},
    "gold/snapshots": {"payload"},
    "gold/reports": set(),
}


def utc_date(value: Optional[datetime] = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def _encode_value(value: Any) -> Any:
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    return value


def _decode_value(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except (TypeError, ValueError):
        return value


class LocalParquetStore:
    """Reads and writes the bronze/silver/gold Parquet lake."""

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def table_dir(self, layer: str, table: str) -> Path:
        self._check_layer(layer)
        return self.data_dir / layer / table

    def partition_dir(self, layer: str, table: str, partition_date: str) -> Path:
        return self.table_dir(layer, table) / f"dt={partition_date}"

    def _check_layer(self, layer: str) -> None:
        if layer not in LAYERS:
            raise ValueError(f"Unknown storage layer '{layer}' (expected one of {LAYERS})")

    # ------------------------------------------------------------------ write
    def write(
        self,
        layer: str,
        table: str,
        records: Sequence[Dict[str, Any]],
        run_id: Optional[str] = None,
        partition_date: Optional[str] = None,
    ) -> Optional[Path]:
        """Append one Parquet part file. Returns None when there is nothing to write."""
        if not records:
            return None
        self._check_layer(layer)
        partition_date = partition_date or utc_date()
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        frame = pd.DataFrame(list(records))
        encoded = JSON_COLUMNS.get(f"{layer}/{table}", set())
        for column in frame.columns:
            values = frame[column]
            if column in encoded or values.map(lambda v: isinstance(v, (list, dict, tuple))).any():
                frame[column] = values.map(_encode_value)
        frame["_partition"] = partition_date
        frame["_run_id"] = run_id
        frame["_ingested_at"] = datetime.now(timezone.utc).isoformat()

        target = self.partition_dir(layer, table, partition_date) / f"part-{run_id}.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            frame.to_parquet(temporary, engine="pyarrow", index=False, compression="zstd")
            # Validate before exposing the partition to readers. A truncated
            # or schema-corrupt part is never promoted to the final filename.
            written = pd.read_parquet(temporary)
            if len(written) != len(frame):
                raise ValueError(
                    f"Parquet validation failed for {target.name}: "
                    f"{len(written)} rows written, {len(frame)} expected"
                )
            missing = set(frame.columns) - set(written.columns)
            if missing:
                raise ValueError(
                    f"Parquet validation failed for {target.name}: missing columns {sorted(missing)}"
                )
            os.replace(temporary, target)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        logger.info("Wrote %d rows to %s", len(frame), target.relative_to(self.data_dir))
        return target

    # ------------------------------------------------------------------- read
    def list_parts(
        self,
        layer: str,
        table: str,
        since_days: Optional[int] = None,
        until_days: Optional[int] = None,
    ) -> List[Path]:
        root = self.table_dir(layer, table)
        if not root.exists():
            return []
        today = datetime.now(timezone.utc).date()
        cutoff = today - timedelta(days=since_days) if since_days is not None else None
        ceiling = today - timedelta(days=until_days) if until_days is not None else None
        parts: List[Path] = []
        for directory in sorted(root.glob("dt=*")):
            raw = directory.name.split("=", 1)[-1]
            try:
                partition = date.fromisoformat(raw)
            except ValueError:
                partition = None
            if cutoff and (partition is None or partition < cutoff):
                continue
            if ceiling and partition is not None and partition > ceiling:
                continue
            parts.extend(sorted(directory.glob("part-*.parquet")))
        return parts

    def read_frame(
        self,
        layer: str,
        table: str,
        since_days: Optional[int] = None,
        columns: Optional[Iterable[str]] = None,
        decode: bool = True,
    ) -> pd.DataFrame:
        parts = self.list_parts(layer, table, since_days=since_days)
        if not parts:
            return pd.DataFrame(columns=list(columns) if columns else None)
        frames = []
        for path in parts:
            try:
                frames.append(pd.read_parquet(path, columns=list(columns) if columns else None))
            except (OSError, ValueError) as exc:
                logger.warning("Skipping unreadable parquet part %s: %s", path, exc)
        if not frames:
            return pd.DataFrame(columns=list(columns) if columns else None)
        frame = pd.concat(frames, ignore_index=True)
        key = next(
            (c for c in ("id", "event_id", "arc_id", "report_id", "window") if c in frame.columns),
            None,
        )
        if key:
            frame = frame.drop_duplicates(subset=[key], keep="last")
        if decode:
            for column in JSON_COLUMNS.get(f"{layer}/{table}", set()):
                if column in frame.columns:
                    frame[column] = frame[column].map(_decode_value)
        return frame

    def read(
        self,
        layer: str,
        table: str,
        since_days: Optional[int] = None,
        columns: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        frame = self.read_frame(layer, table, since_days=since_days, columns=columns)
        if frame.empty:
            return []
        return frame.to_dict(orient="records")

    def read_latest(
        self,
        layer: str,
        table: str,
        since_days: Optional[int] = None,
        columns: Optional[Iterable[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Latest copy of every row keyed by id/event_id (rows are already deduped)."""
        return self.read(layer, table, since_days=since_days, columns=columns)

    # --------------------------------------------------------------- lifecycle
    def prune(self, layer: str, keep_days: int) -> int:
        """Delete partition directories older than keep_days for one layer."""
        self._check_layer(layer)
        root = self.data_dir / layer
        if not root.exists():
            return 0
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(keep_days, 0))
        removed = 0
        for directory in root.glob("*/dt=*"):
            try:
                partition = date.fromisoformat(directory.name.split("=", 1)[-1])
            except ValueError:
                continue
            if partition < cutoff:
                for part in directory.glob("*.parquet"):
                    part.unlink(missing_ok=True)
                try:
                    directory.rmdir()
                    removed += 1
                except OSError:
                    pass
        if removed:
            logger.info("Pruned %d %s partitions older than %s", removed, layer, cutoff)
        return removed

    def prune_table(self, layer: str, table: str, keep_days: int) -> int:
        """Delete partitions older than keep_days for one table."""
        self._check_layer(layer)
        root = self.table_dir(layer, table)
        if not root.exists():
            return 0
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=max(keep_days, 0))
        removed = 0
        for directory in root.glob("dt=*"):
            try:
                partition = date.fromisoformat(directory.name.split("=", 1)[-1])
            except ValueError:
                continue
            if partition < cutoff:
                for part in directory.glob("*.parquet"):
                    part.unlink(missing_ok=True)
                try:
                    directory.rmdir()
                    removed += 1
                except OSError:
                    pass
        if removed:
            logger.info(
                "Pruned %d %s/%s partitions older than %s",
                removed,
                layer,
                table,
                cutoff,
            )
        return removed

    def prune_all(self, bronze_days: int, silver_days: int, gold_days: int = 45) -> None:
        self.prune("bronze", bronze_days)
        self.prune("silver", silver_days)
        self.prune("gold", gold_days)

    def stats(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for layer in LAYERS:
            for table_dir in sorted((self.data_dir / layer).glob("*")):
                if not table_dir.is_dir():
                    continue
                parts = list(table_dir.glob("dt=*/part-*.parquet"))
                size = sum(p.stat().st_size for p in parts)
                rows.append(
                    {
                        "layer": layer,
                        "table": table_dir.name,
                        "parts": len(parts),
                        "size_mb": round(size / (1024 * 1024), 2),
                    }
                )
        return rows
