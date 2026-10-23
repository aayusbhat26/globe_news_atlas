"""Hugging Face dataset repository as the shared bronze/silver/gold store.

The repository mirrors the local Parquet lake:

    bronze/raw_articles/dt=YYYY-MM-DD/part-<run_id>.parquet
    bronze/raw_social/dt=YYYY-MM-DD/part-<run_id>.parquet
    silver/articles/dt=YYYY-MM-DD/part-<run_id>.parquet
    silver/article_content/dt=YYYY-MM-DD/part-<run_id>.parquet  (private, opt-in)
    gold/events/dt=YYYY-MM-DD/part-<run_id>.parquet
    gold/event_details/dt=YYYY-MM-DD/part-<run_id>.parquet
    gold/arcs/dt=YYYY-MM-DD/part-<run_id>.parquet
    gold/snapshots/dt=YYYY-MM-DD/part-<run_id>.parquet
    gold/serving/world_1h.json, world_24h.json, ...
    gold/serving/event_details.json, manifest.json
    gold/serving/search_index.sqlite3  (private, opt-in)

Parquet files are the analytics/history layer; the small JSON files under
``gold/serving`` are what the API reads. Crawled article bodies and the FTS
index are only pushed when ``HF_PUSH_CRAWL_TEXT=true`` is used with a private
store.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger("pipeline.storage.huggingface")

DATASET_CARD = """---
pretty_name: Globe News Atlas Data Lake
tags:
  - news
  - geopolitics
  - parquet
  - bronze-silver-gold
---

# Globe News Atlas data lake

This dataset is the persistence layer for the Globe News Atlas pipeline. It is
organised as a medallion (bronze/silver/gold) Parquet lake.

| Layer | Path | Contents |
| --- | --- | --- |
| Bronze | `bronze/raw_articles/`, `bronze/raw_social/` | Raw records exactly as retrieved from GDELT, RSS, Google News, Reddit, Bluesky, USGS, ReliefWeb, NewsAPI and ACLED. |
| Silver | `silver/articles/` | Normalised, deduplicated and geocoded stories with entities and source metadata. |
| Gold | `gold/events/`, `gold/event_details/`, `gold/arcs/`, `gold/snapshots/` | Clustered events, event detail payloads, bilateral relation arcs and windowed snapshot payloads. |
| Serving | `gold/serving/*.json` | Compact JSON snapshots consumed by the API and web client. |

Every table is date-partitioned as `dt=YYYY-MM-DD` and each pipeline run writes
its own `part-<run_id>.parquet` file. Nested values (entities, coverage,
sources) are stored as JSON strings inside the Parquet columns.

Generated automatically by the Globe News Atlas pipeline. Data is retrieved
from public sources; consult the original outlets for licensing.
"""


class HuggingFaceSync:
    def __init__(
        self,
        token: Optional[str] = None,
        repo_id: Optional[str] = None,
        private: bool = True,
        data_dir: Path | str = "data",
        storage_type: str = "dataset",
        push_crawl_text: bool = False,
    ):
        self.token = (token or "").strip()
        self.repo_id = (repo_id or "").strip()
        self.private = private
        self.data_dir = Path(data_dir)
        self.storage_type = "bucket" if (storage_type or "").strip().lower() == "bucket" else "dataset"
        self.is_bucket = self.storage_type == "bucket"
        self.push_crawl_text = bool(push_crawl_text)
        self.enabled = bool(self.token and self.repo_id)

    @classmethod
    def from_settings(cls, settings: Any) -> "HuggingFaceSync":
        return cls(
            token=settings.hf_token,
            repo_id=settings.hf_repo,
            private=settings.hf_private,
            data_dir=settings.data_dir,
            storage_type=getattr(settings, "hf_storage_type", "dataset"),
            push_crawl_text=getattr(settings, "hf_push_crawl_text", False),
        )

    # ------------------------------------------------------------------ helper
    def _api(self):
        from huggingface_hub import HfApi

        return HfApi(token=self.token)

    def ensure_repo(self) -> bool:
        if not self.enabled:
            return False
        try:
            if self.is_bucket:
                from huggingface_hub import bucket_info, create_bucket

                try:
                    bucket_info(self.repo_id, token=self.token)
                    return True
                except Exception:
                    create_bucket(
                        bucket_id=self.repo_id,
                        token=self.token,
                        private=self.private,
                        exist_ok=True,
                    )
            else:
                from huggingface_hub import create_repo

                create_repo(
                    repo_id=self.repo_id,
                    repo_type="dataset",
                    token=self.token,
                    private=self.private,
                    exist_ok=True,
                )
            return True
        except Exception as exc:  # network/auth errors must not break the run
            logger.warning("Could not ensure Hugging Face %s %s: %s", self.storage_type, self.repo_id, exc)
            return False

    def _list_files(self) -> list[str]:
        """List file paths in either a dataset repo or a bucket."""
        if self.is_bucket:
            from huggingface_hub import BucketFile, list_bucket_tree

            return [
                item.path
                for item in list_bucket_tree(self.repo_id, recursive=True, token=self.token)
                if isinstance(item, BucketFile)
            ]
        return self._api().list_repo_files(self.repo_id, repo_type="dataset")

    # -------------------------------------------------------------------- pull
    def pull(
        self,
        since_days: int = 30,
        bronze_days: int = 3,
        layers: Iterable[str] = ("bronze", "silver", "gold"),
    ) -> Dict[str, int]:
        """Download recent Parquet partitions and the latest serving JSON files."""
        counts = {"downloaded": 0, "skipped": 0, "failed": 0}
        if not self.enabled:
            logger.info("Hugging Face pull skipped (HF_TOKEN/HF_DATASET_REPO not set).")
            return counts
        try:
            files = self._list_files()
        except Exception as exc:
            logger.warning("Could not list Hugging Face %s files: %s", self.storage_type, exc)
            counts["failed"] += 1
            return counts

        today = datetime.now(timezone.utc).date()
        cutoffs = {
            "silver": today - timedelta(days=max(since_days, 1)),
            "gold": today - timedelta(days=max(since_days, 1)),
            "bronze": today - timedelta(days=max(bronze_days, 1)),
        }
        wanted = set(layers)

        for remote in files:
            lower = remote.lower()
            if not (lower.endswith(".parquet") or lower.endswith(".json") or lower.endswith(".sqlite3")):
                continue
            layer = remote.split("/", 1)[0]
            if layer not in wanted:
                continue
            if "/dt=" in remote:
                raw_date = remote.split("/dt=", 1)[1].split("/", 1)[0]
                try:
                    partition = date.fromisoformat(raw_date)
                except ValueError:
                    continue
                if partition < cutoffs.get(layer, today - timedelta(days=since_days)):
                    continue
            elif not remote.startswith("gold/serving/"):
                continue

            local_path = self.data_dir / remote
            # Serving JSON is mutable and must refresh on every pull; Parquet
            # partitions are immutable once written.
            is_serving = remote.startswith("gold/serving/")
            if not is_serving and local_path.exists() and local_path.stat().st_size > 0:
                counts["skipped"] += 1
                continue
            try:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                if self.is_bucket:
                    from huggingface_hub import download_bucket_files

                    download_bucket_files(
                        self.repo_id,
                        [(remote, local_path)],
                        token=self.token,
                    )
                else:
                    from huggingface_hub import hf_hub_download

                    hf_hub_download(
                        repo_id=self.repo_id,
                        filename=remote,
                        repo_type="dataset",
                        token=self.token,
                        local_dir=str(self.data_dir),
                    )
                counts["downloaded"] += 1
            except Exception as exc:
                logger.warning("Failed to download %s: %s", remote, exc)
                counts["failed"] += 1
        logger.info("Hugging Face pull: %s", counts)
        return counts

    # -------------------------------------------------------------------- push
    def _local_files(self, run_id: Optional[str], full: bool) -> list:
        files = []
        for path in self.data_dir.rglob("*"):
            if not path.is_file() or path.suffix not in {".parquet", ".json", ".sqlite3"}:
                continue
            relative = path.relative_to(self.data_dir).as_posix()
            if relative.startswith("silver/article_content/") and not self.push_crawl_text:
                continue
            if relative == "gold/serving/search_index.sqlite3" and not self.push_crawl_text:
                continue
            if relative.startswith(("bronze/", "silver/", "gold/")):
                if full or not run_id or run_id in path.name:
                    files.append((path, relative))
        return files

    def push(
        self,
        run_id: Optional[str] = None,
        full: bool = False,
        message: Optional[str] = None,
    ) -> bool:
        """Upload this run's new Parquet parts plus every serving JSON file."""
        if not self.enabled:
            logger.info("Hugging Face push skipped (HF_TOKEN/HF_DATASET_REPO not set).")
            return False
        if not self.ensure_repo():
            return False

        files = self._local_files(run_id, full)
        # Serving files are small and must always be current. The search index
        # can contain crawled article text, so it is opt-in for private stores.
        serving_patterns = ("*.json", "*.sqlite3") if self.push_crawl_text else ("*.json",)
        for pattern in serving_patterns:
            for serving in (self.data_dir / "gold" / "serving").glob(pattern):
                entry = (serving, serving.relative_to(self.data_dir).as_posix())
                if entry[1] not in {rel for _, rel in files}:
                    files.append(entry)
        if not files:
            logger.info("Nothing new to push to Hugging Face.")
            return False

        try:
            if self.is_bucket:
                from huggingface_hub import batch_bucket_files

                additions = [(str(path), remote) for path, remote in files]
                additions.append((DATASET_CARD.encode("utf-8"), "README.md"))
                batch_bucket_files(self.repo_id, add=additions, token=self.token)
            else:
                from huggingface_hub import CommitOperationAdd

                api = self._api()
                operations = [
                    CommitOperationAdd(path_in_repo=remote, path_or_fileobj=str(path))
                    for path, remote in files
                ]
                operations.append(
                    CommitOperationAdd(path_in_repo="README.md", path_or_fileobj=DATASET_CARD.encode("utf-8"))
                )
                api.create_commit(
                    repo_id=self.repo_id,
                    repo_type="dataset",
                    token=self.token,
                    operations=operations,
                    commit_message=message or f"pipeline: update bronze/silver/gold ({run_id or 'full'})",
                )
            logger.info("Pushed %d files to Hugging Face %s %s", len(files), self.storage_type, self.repo_id)
            return True
        except Exception as exc:
            logger.warning("Hugging Face push failed: %s", exc)
            return False

    def push_serving_manifest(self, run_id: Optional[str] = None) -> bool:
        """Upload the final manifest after the push result is known."""
        if not self.enabled:
            return False
        manifest = self.data_dir / "gold" / "serving" / "manifest.json"
        if not manifest.is_file():
            return False
        remote = "gold/serving/manifest.json"
        try:
            if self.is_bucket:
                from huggingface_hub import batch_bucket_files

                batch_bucket_files(
                    self.repo_id,
                    add=[(str(manifest), remote)],
                    token=self.token,
                )
            else:
                from huggingface_hub import CommitOperationAdd

                self._api().create_commit(
                    repo_id=self.repo_id,
                    repo_type="dataset",
                    token=self.token,
                    operations=[
                        CommitOperationAdd(
                            path_in_repo=remote,
                            path_or_fileobj=str(manifest),
                        )
                    ],
                    commit_message=f"pipeline: {run_id or 'latest'} serving manifest",
                )
            logger.info("Pushed final serving manifest to Hugging Face.")
            return True
        except Exception as exc:
            logger.warning("Final serving manifest push failed: %s", exc)
            return False

    # ------------------------------------------------------------------ remote
    def prune_remote(self, bronze_days: int = 14, silver_days: int = 45, gold_days: int = 45) -> int:
        """Delete remote Parquet partitions older than the local retention policy."""
        if not self.enabled:
            return 0
        try:
            files = self._list_files()
            today = datetime.now(timezone.utc).date()
            retention = {"bronze": bronze_days, "silver": silver_days, "gold": gold_days}
            stale = []
            for remote in files:
                if not remote.endswith(".parquet") or "/dt=" not in remote:
                    continue
                layer = remote.split("/", 1)[0]
                if layer not in retention:
                    continue
                raw_date = remote.split("/dt=", 1)[1].split("/", 1)[0]
                try:
                    partition = date.fromisoformat(raw_date)
                except ValueError:
                    continue
                if partition < today - timedelta(days=retention[layer]):
                    stale.append(remote)
            if not stale:
                return 0
            if self.is_bucket:
                from huggingface_hub import batch_bucket_files

                batch_bucket_files(self.repo_id, delete=stale, token=self.token)
            else:
                from huggingface_hub import CommitOperationDelete

                self._api().create_commit(
                    repo_id=self.repo_id,
                    repo_type="dataset",
                    token=self.token,
                    operations=[CommitOperationDelete(path_in_repo=path) for path in stale],
                    commit_message=f"retention: prune {len(stale)} expired partitions",
                )
            logger.info("Pruned %d remote partitions", len(stale))
            return len(stale)
        except Exception as exc:
            logger.warning("Remote prune failed: %s", exc)
            return 0

    # ---------------------------------------------------------------- download
    def download_serving(self, data_root: Path | str | None = None) -> int:
        """Download gold/serving/*.json into <data_root>/gold/serving."""
        if not self.enabled:
            return 0
        root = Path(data_root) if data_root else self.data_dir
        (root / "gold" / "serving").mkdir(parents=True, exist_ok=True)
        try:
            files = [
                path
                for path in self._list_files()
                if path.startswith("gold/serving/") and path.endswith((".json", ".sqlite3"))
            ]
            count = 0
            for remote in files:
                target = root / remote
                target.parent.mkdir(parents=True, exist_ok=True)
                if self.is_bucket:
                    from huggingface_hub import download_bucket_files

                    download_bucket_files(self.repo_id, [(remote, target)], token=self.token)
                else:
                    from huggingface_hub import hf_hub_download

                    hf_hub_download(
                        repo_id=self.repo_id,
                        filename=remote,
                        repo_type="dataset",
                        token=self.token,
                        local_dir=str(root),
                    )
                count += 1
            return count
        except Exception as exc:
            logger.warning("Serving download failed: %s", exc)
            return 0
