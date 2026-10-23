"""Serve the gold-layer JSON artifacts produced by the pipeline.

The pipeline writes compact JSON files to ``data/gold/serving``:

    world_1h.json, world_24h.json, world_7d.json, world_30d.json
    event_details.json, manifest.json

This service caches them by file mtime, so a pipeline run is visible on the
next request without restarting the API. When no local snapshot exists and a
Hugging Face dataset repo is configured, the serving files are downloaded from
the repo on startup.
"""
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger("app.serving")

WINDOWS = ("1h", "24h", "7d", "30d")
SERVING_FILES = tuple(f"world_{window}.json" for window in WINDOWS) + (
    "event_details.json",
    "manifest.json",
    "rewind.json",
    "search_index.sqlite3",
)


def empty_snapshot(window: str) -> Dict[str, Any]:
    return {
        "ts": "",
        "w": window,
        "n": {"e": 0, "a": 0},
        "events": [],
        "arcs": [],
        "available": False,
    }


class ServingStore:
    def __init__(self) -> None:
        self.root = Path(settings.data_dir) / "gold" / "serving"
        self._cache: Dict[str, Any] = {}
        self._mtimes: Dict[str, int] = {}
        self._lock = threading.Lock()
        self.last_refresh_error: Optional[str] = None

    # ------------------------------------------------------------------ reads
    def _read_json(self, name: str) -> Optional[Any]:
        path = self.root / name
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return None

        with self._lock:
            if name in self._cache and self._mtimes.get(name) == mtime:
                return self._cache[name]

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Could not read serving file %s: %s", path, exc)
            with self._lock:
                return self._cache.get(name)

        with self._lock:
            self._cache[name] = payload
            self._mtimes[name] = mtime
        return payload

    def get_snapshot(self, window: str = "24h") -> Dict[str, Any]:
        if window not in WINDOWS:
            window = "24h"
        payload = self._read_json(f"world_{window}.json")
        if not isinstance(payload, dict):
            return empty_snapshot(window)
        snapshot = dict(payload)
        snapshot["w"] = window
        snapshot["available"] = True
        return snapshot

    def get_details(self) -> Dict[str, Dict[str, Any]]:
        payload = self._read_json("event_details.json")
        return payload if isinstance(payload, dict) else {}

    def get_detail(self, event_id: str) -> Optional[Dict[str, Any]]:
        detail = self.get_details().get(event_id)
        return detail if isinstance(detail, dict) else None

    def get_manifest(self) -> Dict[str, Any]:
        payload = self._read_json("manifest.json")
        return payload if isinstance(payload, dict) else {}

    def get_rewind(self) -> Dict[str, Any]:
        payload = self._read_json("rewind.json")
        return payload if isinstance(payload, dict) else {}

    def get_version(self) -> str:
        """Fingerprint of all serving files, used by the SSE endpoint."""
        stamps = []
        for name in SERVING_FILES:
            try:
                stamps.append(str((self.root / name).stat().st_mtime_ns))
            except OSError:
                stamps.append("0")
        return "|".join(stamps)

    def has_data(self) -> bool:
        return any((self.root / f"world_{window}.json").is_file() for window in WINDOWS)

    def has_search_index(self) -> bool:
        return (self.root / "search_index.sqlite3").is_file()

    # ---------------------------------------------------------- HF cold start
    @property
    def _is_bucket(self) -> bool:
        return str(settings.hf_storage_type or "dataset").lower() == "bucket"

    def _list_serving_files(self) -> List[str]:
        if self._is_bucket:
            from huggingface_hub import BucketFile, list_bucket_tree

            return [
                item.path
                for item in list_bucket_tree(settings.hf_repo, recursive=True, token=settings.hf_token)
                if isinstance(item, BucketFile)
                and item.path.startswith("gold/serving/")
                and item.path.endswith((".json", ".sqlite3"))
            ]
        from huggingface_hub import HfApi

        return [
            remote
            for remote in HfApi(token=settings.hf_token).list_repo_files(settings.hf_repo, repo_type="dataset")
            if remote.startswith("gold/serving/") and remote.endswith((".json", ".sqlite3"))
        ]

    def _download_serving_files(self, remote_files: List[str], destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        if self._is_bucket:
            from huggingface_hub import download_bucket_files

            pairs = []
            for remote in remote_files:
                target = destination / remote
                target.parent.mkdir(parents=True, exist_ok=True)
                pairs.append((remote, target))
            download_bucket_files(settings.hf_repo, pairs, token=settings.hf_token)
            return

        from huggingface_hub import hf_hub_download

        for remote in remote_files:
            hf_hub_download(
                repo_id=settings.hf_repo,
                filename=remote,
                repo_type="dataset",
                token=settings.hf_token,
                local_dir=str(destination),
            )

    def ensure_local(self) -> bool:
        """Download gold/serving from Hugging Face when this process starts cold."""
        if self.has_data() and self.has_search_index():
            return True
        return self.refresh_from_hf(force=True) > 0

    def refresh_from_hf(self, force: bool = False) -> int:
        """Pull newer serving JSON from HF (bucket or dataset).

        Used by the periodic refresher when the pipeline runs in a separate
        worker. Remote manifests older than or equal to the local one are
        ignored, so a local scheduler is never overwritten by a stale upload.
        """
        if not (settings.hf_repo and settings.hf_pull_serving):
            self.last_refresh_error = "Hugging Face pull is disabled or not configured"
            return 0
        try:
            remote_files = self._list_serving_files()
            if not remote_files:
                self.last_refresh_error = "No serving files were found in the Hugging Face repository"
                return 0

            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=str(self.root), prefix=".incoming-") as temporary:
                staging = Path(temporary)
                manifest_remote = next(
                    (name for name in remote_files if name.endswith("/manifest.json") or name == "gold/serving/manifest.json"),
                    None,
                )
                if manifest_remote:
                    self._download_serving_files([manifest_remote], staging)
                    remote_manifest_path = staging / manifest_remote
                    remote_manifest = json.loads(remote_manifest_path.read_text(encoding="utf-8"))
                    remote_run = str(remote_manifest.get("run_id") or "")
                    local_run = str(self.get_manifest().get("run_id") or "")
                    if not force and remote_run and remote_run <= local_run:
                        self.last_refresh_error = None
                        return 0

                self._download_serving_files(remote_files, staging)
                for remote in remote_files:
                    source = staging / remote
                    if not source.is_file():
                        continue
                    target = self.root / Path(remote).name
                    os.replace(source, target)
                with self._lock:
                    self._cache.clear()
                    self._mtimes.clear()
                self.last_refresh_error = None
                logger.info(
                    "Refreshed %d serving files from Hugging Face %s %s",
                    len(remote_files),
                    "bucket" if self._is_bucket else "dataset",
                    settings.hf_repo,
                )
                return len(remote_files)
        except Exception as exc:
            message = str(exc)
            if settings.hf_token:
                message = message.replace(settings.hf_token, "[redacted]")
            self.last_refresh_error = f"{type(exc).__name__}: {message[:240]}"
            logger.warning("Could not refresh serving artifacts from Hugging Face: %s", message)
            return 0

    def status(self) -> Dict[str, Any]:
        manifest = self.get_manifest()
        return {
            "available": self.has_data(),
            "generated_at": manifest.get("generated_at"),
            "run_id": manifest.get("run_id"),
            "windows": manifest.get("windows", {}),
            "counts": manifest.get("counts", {}),
            "sources": manifest.get("sources", {}),
            "storage": manifest.get("storage", {}),
            "hf_pull_enabled": bool(settings.hf_repo and settings.hf_pull_serving),
            "last_refresh_error": self.last_refresh_error,
        }


snapshot_service = ServingStore()
