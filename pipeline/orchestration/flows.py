"""End-to-end bronze ➔ silver ➔ gold pipeline orchestration.

One run:

1. pulls recent partitions from the Hugging Face dataset repo,
2. fetches real data from every enabled public source,
3. writes bronze Parquet exactly as retrieved,
4. normalises/enriches into silver Parquet (entities, countries, geocoding),
5. clusters, classifies, scores and summarises into gold Parquet + serving JSON.

No synthetic articles, hash-based geocoding or index-sliced windows are used.
"""
import hashlib
import json
import logging
import math
import os
import re
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pipeline.analytics import DataQualityChecker
from pipeline.config import WINDOWS, settings
from pipeline.dead_letter import dead_letter_handler
from pipeline.ingestion import (
    ACLEDFetcher,
    BlueskyFetcher,
    GDELTDocFetcher,
    GDELTFetcher,
    GoogleNewsFetcher,
    NewsAPIFetcher,
    RedditFetcher,
    ReliefWebFetcher,
    RSSFetcher,
    USGSFetcher,
)
from pipeline.ingestion.schema import canonicalize_url, parse_datetime, stable_id
from pipeline.ingestion.news_crawler import CrawlResult, NewsCrawler
from pipeline.storage.search_index import build_search_index
from pipeline.modelling import (
    Classifier,
    CoverageAnalyser,
    RelationExtractor,
    Scorer,
    SnapshotGenerator,
    StoryClusterer,
    Summariser,
    Verifier,
)
from pipeline.modelling.coverage_analyser import representative_articles
from pipeline.modelling.replay import ReplayBuilder
from pipeline.modelling.snapshot_generator import select_window_events
from pipeline.orchestration.alerts import send_discord_alert
from pipeline.storage import HuggingFaceSync, LocalParquetStore
from pipeline.transforms import (
    Deduplicator,
    Embedder,
    EntityExtractor,
    Geocoder,
    SocialSignalMerger,
)
from pipeline.transforms.country_codes import (
    canonical_countries,
    canonical_country,
    countries_in_text,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline.orchestration.flow")

WINDOW_NAMES: Tuple[str, ...] = ("1h", "24h", "7d", "30d")
CODED_SOURCES = {"gdelt_events"}
CODED_SOURCE_LABEL = "GDELT event record"
OFFICIAL_SOURCES = {"usgs", "reliefweb", "acled"}
SOCIAL_SOURCES = {"reddit", "bluesky"}
CATEGORY_MAP = {"diplomacy": "politics", "humanitarian": "disaster"}
_SILVER_EPHEMERAL_FIELDS = {"content", "content_excerpt", "word_count", "crawled_at"}
CODED_HISTORY_HOURS = 48
MAX_CODED_CANDIDATES = 600
SUMMARY_MAX_CHARS = 320
SUMMARY_CACHE_VERSION = "5"


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, float) and not math.isfinite(value):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "<na>"}:
        return default
    return text


def _normalise_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_iso(value: Any) -> Optional[datetime]:
    text = _text(value)
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = parse_datetime(text)
        if not parsed:
            return None
        try:
            moment = datetime.fromisoformat(parsed)
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _article_ts(article: Dict[str, Any]) -> Optional[datetime]:
    for key in ("published_at", "fetched_at", "first_seen"):
        moment = _parse_iso(article.get(key))
        if moment:
            return moment
    return None


def _outlet(article: Dict[str, Any]) -> str:
    return (
        _text(article.get("outlet"))
        or _text(article.get("domain"))
        or _text(article.get("source"))
        or "Unknown outlet"
    )


def _outlet_key(article: Dict[str, Any]) -> str:
    return (
        _text(article.get("outlet_id"))
        or _text(article.get("domain"))
        or _text(article.get("outlet"))
        or _text(article.get("source"))
    ).lower()


def _sanitise_nested(value: Any) -> Any:
    """Replace NaN/inf and non-JSON values before writing serving files."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _sanitise_nested(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitise_nested(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _sanitise_row(row: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in list(row.items()):
        if isinstance(value, float) and not math.isfinite(value):
            row[key] = None
    return row


def _merge_entities(
    headline: Optional[Dict[str, List[str]]],
    body: Optional[Dict[str, List[str]]],
) -> Dict[str, List[str]]:
    """Merge headline and body entities with the headline first."""
    merged: Dict[str, List[str]] = {}
    for field in ("people", "organizations", "locations", "countries"):
        values: List[str] = []
        seen: set = set()
        for source in (headline or {}, body or {}):
            for value in source.get(field) or []:
                key = str(value).strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                values.append(str(value).strip())
        merged[field] = values
    return merged


class PipelineFlow:
    """Runs the medallion pipeline and keeps the Parquet lake + HF mirror current."""

    def __init__(self, config: Any = None):
        self.settings = config or settings
        self.data_dir = Path(self.settings.data_dir)
        now = datetime.now(timezone.utc)
        self.run_id = now.strftime("%Y%m%dT%H%M%SZ")
        self.partition_date = now.strftime("%Y-%m-%d")
        self.now = now

        self.store = LocalParquetStore(self.data_dir)
        self.hf = HuggingFaceSync.from_settings(self.settings)
        self.serving_dir = self.data_dir / "gold" / "serving"
        self.serving_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_gen = SnapshotGenerator(self.serving_dir)
        self.replay = ReplayBuilder(self.data_dir)
        self.last_error: Optional[Exception] = None

        # Silver transforms
        self.dedup = Deduplicator(
            max_minhash_articles=getattr(self.settings, "dedupe_minhash_max_articles", 20000)
        )
        self.geocoder = Geocoder()
        self.entity_extractor = EntityExtractor()
        self.embedder = Embedder()
        self.social_merger = SocialSignalMerger()
        self.crawler = NewsCrawler()

        # Gold models
        self.clusterer = StoryClusterer(distance_threshold=self.settings.cluster_distance_threshold)
        self.classifier = Classifier()
        self.scorer = Scorer()
        self.coverage_analyser = CoverageAnalyser()
        self.summariser = Summariser()
        self.verifier = Verifier()
        self.relation_extractor = RelationExtractor()
        self.outlet_registry = self._load_outlet_registry()

    def _load_outlet_registry(self) -> Dict[str, Dict[str, Any]]:
        path = Path(__file__).resolve().parents[2] / "seeds" / "outlets.json"
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Could not load outlet directory %s: %s", path, exc)
            return {}
        registry: Dict[str, Dict[str, Any]] = {}
        for record in records if isinstance(records, list) else []:
            for key in (record.get("domain"), record.get("name"), record.get("id")):
                cleaned = _text(key).lower().removeprefix("www.")
                if cleaned:
                    registry.setdefault(cleaned, record)
        return registry

    def _enrich_outlet(self, article: Dict[str, Any]) -> None:
        """Attach seed alignment metadata to articles from key-less aggregators."""
        for key in (
            _text(article.get("domain")).lower().removeprefix("www."),
            _text(article.get("outlet")).lower().removeprefix("www."),
            _text(article.get("outlet_id")).lower(),
        ):
            record = self.outlet_registry.get(key) if key else None
            if not record:
                continue
            article["outlet_id"] = _text(article.get("outlet_id")) or record.get("id", "")
            if _text(article.get("alignment")).lower() in {"", "unrated"}:
                article["alignment"] = record.get("alignment") or "unrated"
            current_outlet = _text(article.get("outlet"))
            if not current_outlet or current_outlet.lower().removeprefix("www.") == key:
                article["outlet"] = record.get("name", "")
            article["country"] = _text(article.get("country")) or record.get("country")
            article["language"] = _text(article.get("language")) or record.get("language")
            return

    # ------------------------------------------------------------------ public
    def run(self) -> Dict[str, Any]:
        logger.info("=== Starting Globe News Atlas pipeline run %s ===", self.run_id)
        self.last_error = None
        try:
            return self._run()
        except Exception as exc:
            self.last_error = exc
            logger.exception("Pipeline run failed")
            dead_letter_handler.record_failure(
                source="pipeline",
                step="run",
                payload={"run_id": self.run_id},
                error_message=str(exc),
                traceback_str=traceback.format_exc(),
            )
            send_discord_alert(f"Pipeline run {self.run_id} failed: {exc}")
            previous = SnapshotGenerator.read_existing(self.serving_dir, "24h")
            return previous or {
                "ts": datetime.now(timezone.utc).isoformat(),
                "w": "24h",
                "n": {"e": 0, "a": 0},
                "events": [],
                "arcs": [],
            }

    # ------------------------------------------------------------------- phases
    def _crawl(self, raw_articles: List[Dict[str, Any]]) -> CrawlResult:
        if not settings.enable_crawler:
            return CrawlResult(stats={"enabled": 0})
        try:
            recent_rows = self.store.read(
                "silver",
                "article_content",
                since_days=settings.crawler_retention_days,
                columns=["canonical_url"],
            )
            recent_urls = {
                str(row.get("canonical_url") or "")
                for row in recent_rows
                if row.get("canonical_url")
            }
            return self.crawler.run(raw_articles, recent_urls)
        except Exception as exc:
            logger.warning("Article crawler failed; continuing without page text: %s", exc)
            return CrawlResult(stats={"enabled": 1, "failed": 1})

    def _build_search_index(
        self,
        snapshots: Dict[str, Dict[str, Any]],
        contexts: Dict[str, Dict[str, Any]],
    ) -> None:
        try:
            content_rows = self.store.read(
                "silver",
                "article_content",
                since_days=settings.crawler_retention_days,
            )
            content_by_article = {
                str(row.get("article_id")): row
                for row in content_rows
                if row.get("article_id")
            }
            path = build_search_index(
                self.serving_dir / "search_index.sqlite3",
                snapshots=snapshots,
                contexts=contexts,
                content_by_article=content_by_article,
            )
            logger.info("Search index: %d events", path)
        except Exception as exc:
            logger.warning("Could not build full-text search index: %s", exc)

    def _run(self) -> Dict[str, Any]:
        pull_counts = self._pull_remote()

        raw_articles, social_items, source_stats = self._ingest()
        crawler_result = self._crawl(raw_articles)
        raw_articles.extend(crawler_result.new_articles)
        source_stats["crawler"] = crawler_result.stats
        logger.info("Bronze: %d articles, %d social posts", len(raw_articles), len(social_items))
        self.store.write("bronze", "raw_articles", raw_articles, self.run_id, self.partition_date)
        self.store.write("bronze", "raw_social", social_items, self.run_id, self.partition_date)
        self._checkpoint_bronze()

        self.crawler.attach_raw_content(raw_articles, crawler_result)
        normalised = self._normalise_articles(raw_articles)
        content_rows = self.crawler.attach_content(normalised, crawler_result)
        if content_rows:
            self.store.write("silver", "article_content", content_rows, self.run_id, self.partition_date)
        silver_history = self.store.read("silver", "articles", since_days=30)
        silver_rows = [
            {key: value for key, value in row.items() if key not in _SILVER_EPHEMERAL_FIELDS}
            for row in normalised
        ]
        self.store.write("silver", "articles", silver_rows, self.run_id, self.partition_date)

        candidates = self._cluster_candidates(normalised, silver_history)
        logger.info(
            "Silver: %d normalised this run, %d crawled article texts, %d clustering candidates",
            len(normalised),
            len(content_rows),
            len(candidates),
        )
        clusters = self._cluster(candidates)
        logger.info("Gold: %d story clusters", len(clusters))

        previous_events = self._read_event_cache()
        previous_details = self._read_detail_cache()
        previous_index = self._previous_event_index(previous_details)
        events, contexts = self._build_events(
            clusters,
            social_items,
            previous_events,
            previous_index=previous_index,
        )
        events = self._merge_historical_events(events, contexts, previous_events, previous_details)

        arcs = self.relation_extractor.extract_relations(
            [
                {
                    "id": event["id"],
                    "title": event["t"],
                    "category": event["cat"],
                    "importance": event["imp"],
                    "countries": contexts[event["id"]].get("countries") or [],
                }
                for event in events
                if contexts.get(event["id"])
            ]
        )

        snapshots = self._build_snapshots(events, arcs)
        wanted_ids = {event["id"] for snapshot in snapshots.values() for event in snapshot.get("events", [])}
        # Replay frames from earlier runs must keep resolving on /v1/events.
        detail_ids = set(wanted_ids) | self._existing_replay_ids()
        details = self._build_details(detail_ids, contexts, previous_details, arcs)

        self._write_gold(events, arcs, snapshots, details, wanted_ids, contexts)

        replay: Optional[Dict[str, Any]] = None
        try:
            replay = self.replay.build(self.now)
            self._write_json("rewind.json", replay)
            details = self._merge_replay_details(details, replay, previous_details)
        except Exception as exc:
            logger.warning("Could not build the replay archive: %s", exc)
        self._write_json("event_details.json", details)
        self._build_search_index(snapshots, contexts)

        quality = DataQualityChecker(self.serving_dir).check_all()
        self._write_manifest(
            events, arcs, snapshots, details, source_stats, pull_counts, quality, False, False,
            replay=replay,
        )
        pushed, pruned = self._finish_storage()
        self._write_manifest(
            events, arcs, snapshots, details, source_stats, pull_counts, quality, pushed, pruned,
            replay=replay,
        )
        if pushed and not self.hf.push_serving_manifest(self.run_id):
            self._write_manifest(
                events,
                arcs,
                snapshots,
                details,
                source_stats,
                pull_counts,
                quality,
                False,
                pruned,
                replay=replay,
            )

        if not any(snapshot.get("events") for snapshot in snapshots.values()):
            send_discord_alert(f"Pipeline run {self.run_id} produced no events for any window.")

        return snapshots.get("24h") or {
            "ts": datetime.now(timezone.utc).isoformat(),
            "w": "24h",
            "n": {"e": 0, "a": 0},
            "events": [],
            "arcs": [],
        }

    # --------------------------------------------------------------- HF / sync
    def _pull_remote(self) -> Dict[str, int]:
        counts = {"downloaded": 0, "skipped": 0, "failed": 0}
        if self.hf.enabled and self.settings.hf_pull_before_run:
            counts = self.hf.pull(
                since_days=self.settings.hf_pull_days,
                bronze_days=min(3, max(self.settings.bronze_retention_days, 1)),
            )
        else:
            logger.info("Hugging Face pull disabled or not configured; using local Parquet lake only.")
        return counts

    def _checkpoint_bronze(self) -> None:
        """Persist raw extraction before silver/gold engineering begins."""
        if not (
            self.hf.enabled
            and self.settings.hf_push_after_run
            and getattr(self.settings, "hf_bronze_checkpoint", True)
        ):
            return
        try:
            pushed = self.hf.push(
                run_id=self.run_id,
                message=f"pipeline: {self.run_id} bronze extraction checkpoint",
            )
            if pushed:
                logger.info("Bronze extraction checkpoint pushed to Hugging Face.")
        except Exception as exc:
            logger.warning("Bronze checkpoint push failed (continuing with engineering): %s", exc)

    def _finish_storage(self) -> Tuple[bool, bool]:
        pushed = False
        if self.hf.enabled and self.settings.hf_push_after_run:
            pushed = self.hf.push(
                run_id=self.run_id,
                message=f"pipeline: {self.run_id} bronze/silver/gold refresh",
            )
        pruned = False
        if not self.hf.enabled or pushed:
            self.store.prune_all(
                bronze_days=self.settings.bronze_retention_days,
                silver_days=self.settings.silver_retention_days,
                gold_days=max(self.settings.silver_retention_days, 45),
            )
            self.store.prune_table(
                "silver",
                "article_content",
                self.settings.crawler_retention_days,
            )
            pruned = True
        elif self.hf.enabled:
            logger.warning("Skipping local retention pruning because the Hugging Face push failed.")
        return pushed, pruned

    # --------------------------------------------------------------- ingestion
    def _fetchers(self) -> List[Any]:
        fetchers: List[Any] = []
        if self.settings.enable_gdelt_events:
            fetchers.append(GDELTFetcher())
        if self.settings.enable_gdelt_doc:
            fetchers.append(GDELTDocFetcher())
        if self.settings.enable_rss:
            fetchers.append(RSSFetcher())
        if self.settings.enable_google_news:
            fetchers.append(GoogleNewsFetcher())
        if self.settings.enable_reddit:
            fetchers.append(RedditFetcher())
        if self.settings.enable_bluesky:
            fetchers.append(BlueskyFetcher())
        if self.settings.enable_usgs:
            fetchers.append(USGSFetcher())
        if self.settings.enable_reliefweb:
            fetchers.append(ReliefWebFetcher())
        if self.settings.enable_newsapi:
            fetchers.append(NewsAPIFetcher())
        if self.settings.enable_acled:
            fetchers.append(ACLEDFetcher())
        return fetchers

    def _ingest(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        fetchers = self._fetchers()
        results: Dict[str, List[Dict[str, Any]]] = {}
        source_stats: Dict[str, Dict[str, Any]] = {
            fetcher.name: {
                "items": 0,
                "articles": 0,
                "social": 0,
                "failed": False,
                "status": "pending",
                "empty": False,
                "skipped": False,
                "partial": False,
                "error": None,
                "skipped_reason": None,
                "per_feed_errors": {},
            }
            for fetcher in fetchers
        }

        if fetchers:
            with ThreadPoolExecutor(max_workers=min(6, len(fetchers))) as pool:
                futures = {pool.submit(fetcher.fetch): fetcher for fetcher in fetchers}
                for future in as_completed(futures):
                    fetcher = futures[future]
                    try:
                        results[fetcher.name] = future.result() or []
                    except Exception as exc:
                        logger.warning("Fetcher %s crashed: %s", fetcher.name, exc)
                        source_stats[fetcher.name].update(
                            failed=True,
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        dead_letter_handler.record_failure(
                            source=fetcher.name,
                            step="ingestion",
                            payload={},
                            error_message=str(exc),
                            traceback_str=traceback.format_exc(),
                        )
                        results[fetcher.name] = []
                        continue
                    health = fetcher.health() if hasattr(fetcher, "health") else {}
                    source_stats[fetcher.name].update(
                        status=health.get("status") or "unknown",
                        failed=bool(health.get("failed")),
                        empty=bool(health.get("empty")),
                        skipped=bool(health.get("skipped")),
                        partial=bool(health.get("partial")),
                        error=health.get("error"),
                        skipped_reason=health.get("skipped_reason"),
                        per_feed_errors=health.get("per_feed_errors") or {},
                    )

        articles: List[Dict[str, Any]] = []
        social: List[Dict[str, Any]] = []
        for name, items in results.items():
            stats = source_stats[name]
            stats["items"] = len(items)
            for item in items:
                if name in SOCIAL_SOURCES:
                    social.append(item)
                    stats["social"] += 1
                else:
                    articles.append(item)
                    stats["articles"] += 1
        return articles, social, source_stats

    # ----------------------------------------------------------------- silver
    def _normalise_articles(self, raw_articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalised: List[Dict[str, Any]] = []
        seen: set = set()
        for raw in raw_articles:
            source = _text(raw.get("source"))
            title = _text(raw.get("title"))
            if not title:
                continue
            identity = _text(raw.get("canonical_url")) or _text(raw.get("id")) or title.lower()
            key = (identity.lower(), _outlet_key(raw))
            if key in seen:
                continue
            seen.add(key)

            article = dict(raw)
            snippet = _text(raw.get("snippet"))
            content = _text(raw.get("content"))
            analysis_body = f"{snippet} {content[:1200]}".strip()
            self._enrich_outlet(article)
            title_entities = self.entity_extractor.extract(title, headline=True)
            body_entities = self.entity_extractor.extract(analysis_body, headline=False)
            entities = _merge_entities(title_entities, body_entities)

            countries: List[str] = []
            metadata = raw.get("source_metadata") if isinstance(raw.get("source_metadata"), dict) else {}
            metadata_countries = metadata.get("countries")
            if isinstance(metadata_countries, list):
                countries.extend(canonical_countries(metadata_countries))
            elif isinstance(metadata_countries, str):
                countries.extend(canonical_countries([metadata_countries]))
            for field in ("country", "actor1_country", "actor2_country"):
                value = metadata.get(field)
                if isinstance(value, str) and source in {"acled", "gdelt_events"}:
                    countries.extend(canonical_countries([value]))
            # Headline countries are trusted datelines; body countries are
            # filtered so an incidental surname ("Jordan") cannot become one.
            title_countries = canonical_countries(
                countries_in_text(title, allow_ambiguous=True)
                + list((title_entities or {}).get("countries") or [])
            )
            body_countries = canonical_countries(
                countries_in_text(snippet, content[:800], allow_ambiguous=False)
                + list((body_entities or {}).get("countries") or [])
            )
            countries = list(dict.fromkeys(countries + title_countries + body_countries))

            raw_category = _text(raw.get("category")).lower()
            article["category"] = CATEGORY_MAP.get(raw_category, raw_category) or None
            article["entities"] = entities
            article["countries"] = countries[:6]
            article["outlet_country"] = canonical_country(raw.get("country"))
            article["is_coded_event"] = source in CODED_SOURCES
            article["social"] = {}

            geo = self.geocoder.geocode_article(article, entities, title_entities)
            if geo:
                article["geo_lat"] = round(float(geo["lat"]), 4)
                article["geo_lng"] = round(float(geo["lng"]), 4)
                article["geo_name"] = _text(geo.get("name")) or None
                article["geo_precision"] = _text(geo.get("precision")) or None
                article["geo_disputed"] = _text(geo.get("is_disputed")) or None
            else:
                article["geo_lat"] = None
                article["geo_lng"] = None
                article["geo_name"] = None
                article["geo_precision"] = None
                article["geo_disputed"] = None

            published = _article_ts(raw) or self.now
            article["first_seen"] = published.isoformat()
            normalised.append(article)
        return normalised

    def _refresh_history_geo(self, rows: List[Dict[str, Any]]) -> None:
        """Re-geocode editorial history so stale or fuzzy locations cannot persist."""
        for row in rows:
            source = _text(row.get("source"))
            if source in CODED_SOURCES or source in OFFICIAL_SOURCES:
                continue
            title = _text(row.get("title"))
            if not title:
                continue
            snippet = _text(row.get("snippet"))
            title_entities = self.entity_extractor.extract(title, headline=True)
            body_entities = self.entity_extractor.extract(snippet, headline=False)
            entities = _merge_entities(title_entities, body_entities)
            metadata = row.get("source_metadata") if isinstance(row.get("source_metadata"), dict) else {}
            metadata_countries = metadata.get("countries")
            if isinstance(metadata_countries, str):
                metadata_countries = [metadata_countries]
            countries = canonical_countries(metadata_countries or [])
            countries = list(dict.fromkeys(
                countries
                + canonical_countries(countries_in_text(title, allow_ambiguous=True))
                + canonical_countries(countries_in_text(snippet, allow_ambiguous=False))
            ))
            row["countries"] = countries[:6]
            geo = self.geocoder.geocode_article(
                {
                    "lat": row.get("lat"),
                    "lng": row.get("lng"),
                    "location_name": row.get("location_name"),
                    "title": title,
                    "snippet": snippet,
                },
                entities,
                title_entities,
            )
            if geo:
                row["geo_lat"] = round(float(geo["lat"]), 4)
                row["geo_lng"] = round(float(geo["lng"]), 4)
                row["geo_name"] = _text(geo.get("name")) or None
                row["geo_precision"] = _text(geo.get("precision")) or None
                row["geo_disputed"] = _text(geo.get("is_disputed")) or None
            else:
                row["geo_lat"] = None
                row["geo_lng"] = None
                row["geo_name"] = None
                row["geo_precision"] = None
                row["geo_disputed"] = None

    def _cluster_candidates(
        self,
        normalised: List[Dict[str, Any]],
        history_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        history = [_sanitise_row(row) for row in history_rows]
        self._refresh_history_geo(history)
        merged: Dict[str, Dict[str, Any]] = {}
        for row in history:
            key = _text(row.get("id"))
            if key:
                merged[key] = row

        for current in normalised:
            key = _text(current.get("id"))
            if not key:
                continue
            previous = merged.get(key)
            if previous:
                previous_first = _parse_iso(previous.get("first_seen"))
                current_first = _parse_iso(current.get("first_seen"))
                if previous_first and (not current_first or previous_first < current_first):
                    current["first_seen"] = previous_first.isoformat()
                if current.get("geo_lat") is None and _number(previous.get("geo_lat")) is not None:
                    for field in ("geo_lat", "geo_lng", "geo_name", "geo_precision", "geo_disputed"):
                        current[field] = previous.get(field)
                if not current.get("countries"):
                    current["countries"] = previous.get("countries") or []
            merged[key] = current

        values = list(merged.values())
        real = [row for row in values if _text(row.get("source")) not in CODED_SOURCES]
        real.sort(
            key=lambda row: (_article_ts(row) or datetime.min.replace(tzinfo=timezone.utc), _text(row.get("id"))),
            reverse=True,
        )
        candidate_limit = max(self.settings.cluster_max_articles, 100)
        if len(real) > candidate_limit:
            logger.warning(
                "Clustering candidate pool truncated: %d available, %d kept. "
                "Raise CLUSTER_MAX_ARTICLES (and DEDUPE_MINHASH_MAX_ARTICLES) to cover the 30-day volume.",
                len(real),
                candidate_limit,
            )
            real = real[:candidate_limit]

        cutoff = self.now - timedelta(hours=CODED_HISTORY_HOURS)
        coded = [
            row
            for row in values
            if _text(row.get("source")) in CODED_SOURCES
            and (_article_ts(row) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        ]
        coded.sort(
            key=lambda row: (_article_ts(row) or datetime.min.replace(tzinfo=timezone.utc), _text(row.get("id"))),
            reverse=True,
        )
        return real + coded[:MAX_CODED_CANDIDATES]

    def _cluster(self, candidates: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        if not candidates:
            return []
        candidates = self.dedup.process_articles(candidates)
        texts = [
            f"{_text(article.get('title'))} {(_text(article.get('content')) or _text(article.get('snippet')))[:1200]}".strip()
            for article in candidates
        ]
        try:
            embeddings = self.embedder.embed(texts)
            clusters = self.clusterer.cluster(candidates, embeddings)
        except Exception as exc:
            logger.warning("Clustering failed (%s); falling back to one story per article.", exc)
            clusters = [[article] for article in candidates]

        # Coded records already represent one CAMEO event each. Their templated
        # titles cluster spuriously ("X: engaged in fighting"), so keep them apart.
        # Official feeds (USGS/ACLED/ReliefWeb) also publish authoritative per-
        # event ids; two distinct ids are never the same story.
        isolated: List[List[Dict[str, Any]]] = []
        for cluster in clusters:
            real = [
                article
                for article in cluster
                if _text(article.get("source")) not in CODED_SOURCES
                and _text(article.get("source")) not in OFFICIAL_SOURCES
            ]
            singles = [
                article
                for article in cluster
                if _text(article.get("source")) in CODED_SOURCES
                or _text(article.get("source")) in OFFICIAL_SOURCES
            ]
            if real:
                isolated.append(real)
            isolated.extend([article] for article in singles)
        return isolated

    # ------------------------------------------------------------------- gold
    def _read_event_cache(self) -> Dict[str, Dict[str, Any]]:
        # Read the full 30-day window, not just two days: windows must be able
        # to merge history that silver no longer holds, and replay frames need
        # their event rows.
        rows = self.store.read("gold", "events", since_days=30)
        cache: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            _sanitise_row(row)
            key = _text(row.get("event_id")) or _text(row.get("id"))
            if key:
                cache[key] = row
        return cache

    def _read_detail_cache(self) -> Dict[str, Dict[str, Any]]:
        rows = self.store.read("gold", "event_details", since_days=30)
        cache: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            _sanitise_row(row)
            key = _text(row.get("event_id")) or _text(row.get("id"))
            if key:
                cache[key] = row
        return cache

    def _existing_replay_ids(self) -> set:
        path = self.serving_dir / "rewind.json"
        if not path.exists():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {
            str(event.get("id"))
            for frame in payload.get("frames") or []
            for event in frame.get("events") or []
            if isinstance(event, dict) and event.get("id")
        }

    def _merge_replay_details(
        self,
        details: Dict[str, Dict[str, Any]],
        replay: Optional[Dict[str, Any]],
        previous_details: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Ensure every replay frame id has a detail row."""
        if not replay:
            return details
        merged = dict(details)
        for frame in replay.get("frames") or []:
            for event in frame.get("events") or []:
                event_id = _text(event.get("id")) if isinstance(event, dict) else ""
                if not event_id or event_id in merged:
                    continue
                previous = previous_details.get(event_id)
                if isinstance(previous, dict):
                    detail = dict(_sanitise_row(previous))
                    detail["id"] = event_id
                    detail.setdefault("revision", 1)
                    merged[event_id] = detail
        return merged

    def _previous_event_index(self, previous_details: Dict[str, Dict[str, Any]]) -> Dict[tuple, str]:
        """Index previous details by source URL and title+outlet.

        Reusing an existing id when the same source URL/title already has a
        detail keeps /v1/events links and replay frames stable across runs.
        """
        index: Dict[tuple, str] = {}
        for event_id, detail in (previous_details or {}).items():
            if not _text(event_id):
                continue
            for source in detail.get("sources") or []:
                if not isinstance(source, dict):
                    continue
                url = canonicalize_url(_text(source.get("url")))
                if url:
                    index.setdefault(("url", url.lower()), event_id)
                title = _normalise_text(_text(source.get("title")))
                outlet = _text(source.get("outlet_name") or source.get("outlet")).lower()
                if title:
                    index.setdefault(("title", title, outlet), event_id)
            title = _normalise_text(_text(detail.get("title")))
            outlet = _text(detail.get("source") or detail.get("outlet")).lower()
            if title:
                index.setdefault(("title", title, outlet), event_id)
        return index

    def _matched_event_id(
        self,
        article: Dict[str, Any],
        previous_index: Optional[Dict[tuple, str]],
        avoid: Optional[set] = None,
    ) -> Optional[str]:
        if not previous_index:
            return None
        candidates = []
        url = canonicalize_url(_text(article.get("canonical_url")) or _text(article.get("url")))
        if url:
            candidates.append(("url", url.lower()))
        title = _normalise_text(_text(article.get("title")))
        outlet = _outlet(article).lower()
        if title:
            candidates.append(("title", title, outlet))
        for key in candidates:
            event_id = previous_index.get(key)
            if event_id and (not avoid or event_id not in avoid):
                return event_id
        return None

    def _event_id(
        self,
        cluster: List[Dict[str, Any]],
        previous_index: Optional[Dict[tuple, str]] = None,
        avoid: Optional[set] = None,
    ) -> str:
        ordered = sorted(
            cluster,
            key=lambda article: (
                _article_ts(article) or datetime.min.replace(tzinfo=timezone.utc),
                _text(article.get("id")),
            ),
        )
        # Official feeds publish authoritative event ids. Deriving the event id
        # from them makes USGS/ACLED/ReliefWeb ids stable and distinct.
        for article in ordered:
            source = _text(article.get("source"))
            if source in OFFICIAL_SOURCES or source in CODED_SOURCES:
                source_id = _text(article.get("source_id")) or _text(article.get("id"))
                if source_id:
                    return "evt-" + stable_id("event", source, source_id)[:20]
        # Reuse an existing id when the same URL/title already has a detail.
        for article in ordered:
            matched = self._matched_event_id(article, previous_index, avoid)
            if matched:
                return matched
        for article in ordered:
            if _text(article.get("source")) not in CODED_SOURCES and _text(article.get("id")):
                candidate = "evt-" + stable_id("event", article.get("id"))[:20]
                if not avoid or candidate not in avoid:
                    return candidate
        if ordered and _text(ordered[0].get("id")):
            candidate = "evt-" + stable_id("event", ordered[0].get("id"))[:20]
            if not avoid or candidate not in avoid:
                return candidate
        return "evt-" + stable_id("event", self.run_id, _text(ordered[0].get("id")) if ordered else "")[:20]

    def _primary_article(self, cluster: List[Dict[str, Any]]) -> Dict[str, Any]:
        ordered = sorted(
            cluster,
            key=lambda article: (_article_ts(article) or datetime.min.replace(tzinfo=timezone.utc), _text(article.get("id"))),
            reverse=True,
        )
        for article in ordered:
            if _text(article.get("source")) not in CODED_SOURCES:
                return article
        return ordered[0]

    def _choose_geo(self, cluster: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        def entry_for(article: Dict[str, Any]):
            lat = _number(article.get("geo_lat"))
            lng = _number(article.get("geo_lng"))
            if lat is None or lng is None:
                return None
            precision = _text(article.get("geo_precision")) or "region"
            name = _text(article.get("geo_name")) or _text(article.get("location_name"))
            timestamp = _article_ts(article) or datetime.min.replace(tzinfo=timezone.utc)
            return (precision, lat, lng, name, timestamp)

        # The event title and summary come from the primary article, so its
        # location is the only defensible anchor. Taking a city from a
        # secondary article is how a Colombia story ended up plotted in China.
        primary_entry = entry_for(self._primary_article(cluster))
        if primary_entry:
            precision, lat, lng, name, _ = primary_entry
            return {"lat": round(lat, 4), "lng": round(lng, 4), "precision": precision, "name": name}

        entries = [entry for entry in (entry_for(article) for article in cluster) if entry]
        if not entries:
            return None

        rank = {"city": 0, "region": 1, "country": 2}
        best_rank = min(rank.get(entry[0], 1) for entry in entries)
        pool = [entry for entry in entries if rank.get(entry[0], 1) == best_rank]
        counter = Counter((round(entry[1], 2), round(entry[2], 2)) for entry in pool)
        (best_lat, best_lng), _ = counter.most_common(1)[0]
        matching = [
            entry for entry in pool if (round(entry[1], 2), round(entry[2], 2)) == (best_lat, best_lng)
        ]
        matching.sort(key=lambda entry: entry[4], reverse=True)
        precision, lat, lng, name, _ = matching[0]
        return {"lat": round(lat, 4), "lng": round(lng, 4), "precision": precision, "name": name}

    def _countries(self, cluster: List[Dict[str, Any]]) -> List[str]:
        counter: Counter = Counter()
        for article in cluster:
            for country in article.get("countries") or []:
                name = canonical_country(country)
                if name:
                    counter[name] += 1
        return [name for name, _ in counter.most_common(6)]

    def _status(self, hours_since_update: float, classification: Dict[str, Any]) -> str:
        if hours_since_update <= 1:
            return "breaking"
        if hours_since_update <= 6:
            return "developing"
        if classification.get("status") == "developing" and hours_since_update <= 24:
            return "developing"
        return "ongoing"

    def _summarise(
        self,
        event_id: str,
        cluster: List[Dict[str, Any]],
        title: str,
        previous: Dict[str, Dict[str, Any]],
        allow_llm: bool,
    ) -> Tuple[Dict[str, Any], bool]:
        source_ids = sorted({_text(article.get("id")) for article in cluster if _text(article.get("id"))})
        source_sig = stable_id("sig", SUMMARY_CACHE_VERSION, *source_ids[:80])
        cached = previous.get(event_id)
        if cached and _text(cached.get("source_sig")) == source_sig and _text(cached.get("summary")):
            return (
                {
                    "summary": _text(cached.get("summary")),
                    "method": _text(cached.get("summary_method")) or "cached",
                    "confidence": _number(cached.get("confidence")) or 0.5,
                    "source_sig": source_sig,
                },
                False,
            )

        info = self.summariser.summarise_hover(cluster, title=title, allow_llm=allow_llm)
        method = _text(info.get("method")) or "extractive"
        return (
            {
                "summary": _text(info.get("summary")),
                "method": method,
                "confidence": float(info.get("confidence") or 0.0),
                "source_sig": source_sig,
            },
            method.startswith("llm:"),
        )

    def _build_events(
        self,
        clusters: List[List[Dict[str, Any]]],
        social_items: List[Dict[str, Any]],
        previous_events: Dict[str, Dict[str, Any]],
        previous_index: Optional[Dict[tuple, str]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        events: List[Dict[str, Any]] = []
        contexts: Dict[str, Dict[str, Any]] = {}
        llm_budget = self.settings.max_llm_summaries if self.settings.enable_llm_summaries else 0
        initial_budget = llm_budget

        clusters = sorted(
            [cluster for cluster in clusters if cluster],
            key=lambda cluster: (
                len(cluster),
                max(
                    (_article_ts(article) or datetime.min.replace(tzinfo=timezone.utc) for article in cluster),
                    default=datetime.min.replace(tzinfo=timezone.utc),
                ),
            ),
            reverse=True,
        )

        for cluster in clusters:
            primary = self._primary_article(cluster)
            title = _text(primary.get("title")) or "Untitled event"
            snippet = _text(primary.get("snippet"))
            content = _text(primary.get("content"))
            analysis_body = snippet if len(snippet) >= 200 else f"{snippet} {content[:800]}".strip()
            event_id = self._event_id(cluster, previous_index, avoid=set(contexts))
            if event_id in contexts:
                continue

            classification = self.classifier.classify(
                title,
                analysis_body,
                pre_assigned_cat=_text(primary.get("category")) or None,
                source_count=len(cluster),
            )
            coverage = self.coverage_analyser.analyse(cluster)
            social = self.social_merger.score_cluster(cluster, social_items)
            countries = self._countries(cluster)
            geo = self._choose_geo(cluster)

            stamps = [stamp for stamp in (_article_ts(article) for article in cluster) if stamp]
            first_seen = min(stamps) if stamps else self.now
            last_updated = max(stamps) if stamps else first_seen
            if first_seen > self.now:
                first_seen = self.now
            if last_updated > self.now:
                last_updated = self.now
            if first_seen > last_updated:
                first_seen = last_updated
            hours_since_update = max((self.now - last_updated).total_seconds() / 3600.0, 0.0)

            scoring = self.scorer.score_event(
                outlet_count=coverage["distinct_outlets"],
                social_buzz=social["social_buzz_score"],
                severity=classification["severity"],
                source_count=coverage["source_count"],
                has_official_source=coverage["has_official_source"],
                hours_since_update=hours_since_update,
            )
            status = self._status(hours_since_update, classification)

            has_summary_material = len(cluster) > 1 or len(snippet) >= 120
            summary_info, used_llm = self._summarise(
                event_id,
                cluster,
                title,
                previous_events,
                allow_llm=llm_budget > 0 and has_summary_material,
            )
            if used_llm:
                llm_budget -= 1

            location_name = (geo or {}).get("name") or (countries[0] if countries else "")
            event = {
                "id": event_id,
                "lat": (geo or {}).get("lat"),
                "lng": (geo or {}).get("lng"),
                "cat": classification["category"],
                "imp": scoring["importance"],
                "t": title[:160],
                "at": last_updated.isoformat(),
                "oc": coverage["distinct_outlets"],
                "sp": coverage["spectrum"],
                "st": status,
                "sb": social["social_buzz_score"],
                "ss": scoring["is_single_source"],
                "cg": coverage["has_coverage_gap"],
                "cw": bool(classification["content_warning"]),
                "sum": _text(summary_info["summary"])[:SUMMARY_MAX_CHARS],
                "loc": location_name[:120],
                "gp": (geo or {}).get("precision") or "",
                "src": _outlet(primary)[:80],
            }

            contexts[event_id] = {
                "cluster": cluster,
                "primary": primary,
                "title": title,
                "countries": countries,
                "geo": geo,
                "first_seen": first_seen,
                "last_updated": last_updated,
                "classification": classification,
                "coverage": coverage,
                "social": social,
                "scoring": scoring,
                "summary": summary_info,
                "status": status,
            }
            events.append(event)

        logger.info(
            "Built %d events (%d LLM summaries used, %d budget left)",
            len(events),
            max(initial_budget - llm_budget, 0),
            max(llm_budget, 0),
        )
        return events, contexts

    def _merge_historical_events(
        self,
        events: List[Dict[str, Any]],
        contexts: Dict[str, Dict[str, Any]],
        previous_events: Dict[str, Dict[str, Any]],
        previous_details: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Add still-relevant gold events that silver history no longer holds.

        This is what keeps 7d/30d honest when the pull window is short: other
        windows may show whatever history genuinely exists, and the span fields
        disclose when that is less than requested.
        """
        cutoff = self.now - timedelta(days=30)
        current_ids = {event.get("id") for event in events}
        current_titles = {
            (_normalise_text(_text(event.get("t"))), _text(event.get("src")).lower())
            for event in events
        }
        merged = list(events)
        for event_id, row in previous_events.items():
            if not event_id or event_id in current_ids or event_id in contexts:
                continue
            _sanitise_row(row)
            if _text(row.get("src")) == CODED_SOURCE_LABEL:
                continue
            lat, lng = _number(row.get("lat")), _number(row.get("lng"))
            if lat is None or lng is None:
                continue
            stamp = _parse_iso(row.get("at") or row.get("last_updated"))
            if not stamp or stamp < cutoff or stamp > self.now + timedelta(hours=1):
                continue
            title_key = (
                _normalise_text(_text(row.get("t") or row.get("title"))),
                _text(row.get("src")).lower(),
            )
            if title_key in current_titles:
                continue
            event = {
                "id": event_id,
                "lat": round(lat, 4),
                "lng": round(lng, 4),
                "cat": _text(row.get("cat") or row.get("category")) or "other",
                "imp": _number(row.get("imp") or row.get("importance")) or 0.0,
                "t": _text(row.get("t") or row.get("title"))[:160],
                "at": stamp.isoformat(),
                "oc": int(_number(row.get("oc")) or 0),
                "sp": row.get("sp") or row.get("spectrum") or {},
                "st": _text(row.get("st") or row.get("status")) or "ongoing",
                "sb": _number(row.get("sb")) or 0.0,
                "ss": bool(row.get("ss")),
                "cg": bool(row.get("cg")),
                "cw": bool(row.get("cw")),
                "sum": _text(row.get("sum") or row.get("summary")),
                "loc": _text(row.get("loc") or row.get("location_name"))[:120],
                "gp": _text(row.get("gp") or row.get("geo_precision")),
                "src": _text(row.get("src"))[:80],
                "article_count": int(_number(row.get("article_count")) or 0),
                "source_count": int(_number(row.get("source_count")) or 0),
            }
            merged.append(event)
            current_ids.add(event_id)
            contexts[event_id] = {
                "historical": True,
                "event": event,
                "previous_detail": previous_details.get(event_id),
                "countries": row.get("countries") or [],
            }
        if len(merged) > len(events):
            logger.info(
                "Merged %d historical gold events into the 30-day snapshot pool",
                len(merged) - len(events),
            )
        return merged

    # -------------------------------------------------------------- snapshots
    def _snapshot_cap(self, window: str) -> int:
        base = max(self.settings.max_snapshot_events, 20)
        if window == "7d":
            return max(self.settings.max_snapshot_events_7d, base)
        if window == "30d":
            return max(self.settings.max_snapshot_events_30d, base)
        return base

    def _window_events(
        self,
        events: List[Dict[str, Any]],
        window: str,
        required_ids: Optional[Iterable[str]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        # CAMEO rows are machine-coded conflict signals, not editorial stories.
        # They remain in the lake for relations and analysis but must not crowd
        # real reporting out of the public snapshots.
        selected, total, _ = select_window_events(
            events,
            self.now,
            window,
            self._snapshot_cap(window),
            required_ids=required_ids,
            coded_label=CODED_SOURCE_LABEL,
        )
        return selected, total

    def _build_snapshots(
        self, events: List[Dict[str, Any]], arcs: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        snapshots: Dict[str, Dict[str, Any]] = {}
        required_ids: List[str] = []
        for window in WINDOW_NAMES:
            selected, total_available, meta = select_window_events(
                events,
                self.now,
                window,
                self._snapshot_cap(window),
                required_ids=required_ids,
                coded_label=CODED_SOURCE_LABEL,
            )
            if not selected:
                previous = SnapshotGenerator.read_existing(self.serving_dir, window)
                if previous and previous.get("events"):
                    logger.warning("No %s events this run; keeping previous %s snapshot.", window, window)
                    snapshots[window] = previous
                    continue
            # Carry every narrower-window id into the next window. This is the
            # invariant that previously failed when a 7d cap of 600 dropped 48
            # of the 400 ids shown in 24h.
            required_ids = [str(event.get("id")) for event in selected if event.get("id")]
            snapshots[window] = self.snapshot_gen.generate(
                selected,
                arcs,
                window_name=window,
                generated_at=self.now.isoformat(),
                total_events=total_available,
                window_meta=meta,
            )
            logger.info(
                "Snapshot %s: %d shown of %d available, span %.1fh (complete=%s)",
                window,
                len(selected),
                total_available,
                float(meta.get("span_hours") or 0.0),
                meta.get("span_complete"),
            )
        return snapshots

    # ---------------------------------------------------------------- details
    def _timeline(self, cluster: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ordered = sorted(
            cluster,
            key=lambda article: _article_ts(article) or datetime.min.replace(tzinfo=timezone.utc),
        )
        entries: List[Dict[str, Any]] = []
        seen: set = set()
        for article in ordered:
            title = _text(article.get("title"))
            outlet = _outlet(article)
            stamp = _article_ts(article)
            if not title or not stamp:
                continue
            key = (outlet.lower(), title.lower())
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "timestamp": stamp.isoformat(),
                    "description": f'{outlet} reports: "{title[:180]}"',
                    "source_count": 1,
                }
            )
            if len(entries) >= 6:
                break
        return entries

    def _coverage_detail(self, cluster: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        reps = representative_articles(cluster)
        camps: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for article in reps:
            source = _text(article.get("source"))
            if source in CODED_SOURCES or source in OFFICIAL_SOURCES:
                continue
            camp = self.coverage_analyser.CAMP_MAPPING.get(
                _text(article.get("alignment")).lower() or "unrated",
                "unrated",
            )
            camps[camp].append(article)

        result: List[Dict[str, Any]] = []
        for camp in ("left", "centre", "right", "unrated"):
            items = sorted(
                camps.get(camp, []),
                key=lambda article: _article_ts(article) or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            if not items:
                continue
            outlets = {_outlet_key(article) for article in items if _outlet_key(article)}
            headlines: List[Dict[str, str]] = []
            seen: set = set()
            for article in items:
                title = _text(article.get("title"))
                url = _text(article.get("canonical_url")) or _text(article.get("url"))
                outlet = _outlet(article)
                if not title or not url or (outlet.lower(), title.lower()) in seen:
                    continue
                seen.add((outlet.lower(), title.lower()))
                headlines.append({"title": title[:180], "outlet": outlet, "url": url})
                if len(headlines) >= 3:
                    break
            result.append(
                {
                    "camp": camp,
                    "outlet_count": len(outlets),
                    "article_count": len(items),
                    "framing_note": f"{len(outlets)} {camp}-rated outlet(s) reported this event.",
                    "sample_headlines": headlines,
                }
            )
        return result

    def _article_excerpt(self, article: Dict[str, Any]) -> str:
        title = _normalise_text(_text(article.get("title")))
        for field in ("content", "snippet"):
            text = re.sub(r"^\[headline only\]\s*", "", _text(article.get(field)), flags=re.IGNORECASE).strip()
            if len(text) < 40:
                continue
            cleaned = _normalise_text(text)
            if not cleaned or cleaned == title:
                continue
            if (cleaned in title or title in cleaned) and abs(len(cleaned) - len(title)) < 40:
                continue
            return text[:700].strip()
        return ""

    def _excerpt(self, cluster: List[Dict[str, Any]]) -> str:
        ordered = sorted(
            cluster,
            key=lambda article: _text(article.get("source")) in CODED_SOURCES,
        )
        for article in ordered:
            excerpt = self._article_excerpt(article)
            if excerpt:
                return excerpt
        return ""

    def _sources(self, cluster: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        reps = sorted(
            representative_articles(cluster),
            key=lambda article: (
                not bool(article.get("via_google_news") or _text(article.get("source")) == "google_news"),
                _text(article.get("source")) not in CODED_SOURCES,
                _article_ts(article) or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        sources: List[Dict[str, Any]] = []
        seen: set = set()
        seen_title_outlet: set = set()
        for article in reps:
            url = _text(article.get("canonical_url")) or _text(article.get("url"))
            if not url or url.lower() in seen:
                continue
            title = _text(article.get("title"))
            outlet_key = _outlet(article).strip().lower()
            title_outlet = (_normalise_text(title), outlet_key)
            if title_outlet in seen_title_outlet:
                continue
            seen_title_outlet.add(title_outlet)
            seen.add(url.lower())
            snippet = self._article_excerpt(article)
            published = _article_ts(article)
            metadata = article.get("source_metadata") if isinstance(article.get("source_metadata"), dict) else {}
            sources.append(
                {
                    "outlet_name": _outlet(article),
                    "url": url,
                    "alignment": _text(article.get("alignment")) or "unrated",
                    "title": title[:200],
                    "snippet": snippet[:280],
                    "published_at": published.isoformat() if published else None,
                    "via_google_news": bool(
                        article.get("via_google_news")
                        or _text(article.get("source")) == "google_news"
                        or metadata.get("via_google_news")
                    ),
                }
            )
            if len(sources) >= 12:
                break
        return sources

    def _detail(self, event: Dict[str, Any], context: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cluster = context["cluster"]
        summary_text = context["summary"]["summary"]
        revision = int(previous.get("revision") or 1) if previous else 1
        if previous and _text(previous.get("summary")) and _text(previous.get("summary")) != summary_text:
            revision += 1
        corrections = previous.get("corrections") if previous else []
        if not isinstance(corrections, list):
            corrections = []

        geo = context["geo"] or {}
        location_name = geo.get("name") or (context["countries"][0] if context["countries"] else "")
        sources = self._sources(cluster)
        source_total = max(int(context["coverage"]["source_count"] or 0), len(sources))
        return {
            "id": event["id"],
            "title": context["title"],
            "status": context["status"],
            "category": event["cat"],
            "severity": context["classification"]["severity"],
            "first_reported": context["first_seen"].isoformat(),
            "last_updated": context["last_updated"].isoformat(),
            "summary": summary_text,
            "summary_method": context["summary"]["method"],
            "confidence": round(float(context["summary"]["confidence"] or context["scoring"]["confidence"]), 2),
            "excerpt": self._excerpt(cluster),
            "timeline": self._timeline(cluster),
            "coverage": self._coverage_detail(cluster),
            "sources": sources,
            "sources_total": source_total,
            "sources_shown": len(sources),
            "sources_sampled": len(sources) < source_total,
            "corrections": corrections,
            "revision": revision,
            "lat": event.get("lat"),
            "lng": event.get("lng"),
            "geo_precision": geo.get("precision") or "",
            "location_name": location_name,
            "reddit_threads": context["social"]["reddit_threads"],
            "bluesky_posts": context["social"]["bluesky_posts"],
            "outlet_count": context["coverage"]["distinct_outlets"],
            "article_count": len(cluster),
            "source_count": context["coverage"]["source_count"],
            "is_single_source": context["scoring"]["is_single_source"],
            "has_coverage_gap": context["coverage"]["has_coverage_gap"],
            "has_official_source": context["coverage"]["has_official_source"],
            "content_warning": context["classification"]["content_warning"],
            "related_event_ids": [],
            "related_relation_ids": [],
            "countries": context["countries"],
            "spectrum": context["coverage"]["spectrum"],
            "source_sig": context["summary"]["source_sig"],
        }

    def _historical_detail(self, event_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        event = context.get("event") or {}
        stamp = _text(event.get("at"))
        return {
            "id": event_id,
            "title": _text(event.get("t")),
            "status": _text(event.get("st")) or "ongoing",
            "category": _text(event.get("cat")) or "other",
            "severity": "low",
            "first_reported": stamp,
            "last_updated": stamp,
            "summary": _text(event.get("sum")),
            "summary_method": "cached",
            "confidence": 0.5,
            "excerpt": "",
            "timeline": [],
            "coverage": [],
            "sources": [],
            "corrections": [],
            "revision": 1,
            "lat": event.get("lat"),
            "lng": event.get("lng"),
            "geo_precision": _text(event.get("gp")),
            "location_name": _text(event.get("loc")),
            "reddit_threads": 0,
            "bluesky_posts": 0,
            "outlet_count": int(event.get("oc") or 0),
            "article_count": int(event.get("article_count") or 0),
            "source_count": int(event.get("source_count") or 0),
            "sources_total": int(event.get("source_count") or 0),
            "sources_shown": 0,
            "is_single_source": bool(event.get("ss")),
            "has_coverage_gap": bool(event.get("cg")),
            "has_official_source": False,
            "content_warning": None,
            "related_event_ids": [],
            "related_relation_ids": [],
            "countries": list(context.get("countries") or []),
            "spectrum": event.get("sp") or {},
            "source_sig": "",
        }

    def _build_details(
        self,
        wanted_ids: Iterable[str],
        contexts: Dict[str, Dict[str, Any]],
        previous_details: Dict[str, Dict[str, Any]],
        arcs: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        wanted = [
            event_id
            for event_id in wanted_ids
            if event_id in contexts or event_id in previous_details
        ]
        details: Dict[str, Dict[str, Any]] = {}
        for event_id in wanted:
            if event_id not in contexts:
                detail = dict(_sanitise_row(previous_details[event_id]))
                detail["id"] = event_id
                detail.setdefault("revision", 1)
                detail.setdefault("corrections", [])
                detail.setdefault("related_event_ids", [])
                detail.setdefault("related_relation_ids", [])
                details[event_id] = detail
                continue
            context = contexts[event_id]
            if context.get("historical"):
                detail = context.get("previous_detail")
                if isinstance(detail, dict):
                    detail = dict(_sanitise_row(detail))
                else:
                    detail = self._historical_detail(event_id, context)
                detail["id"] = event_id
                detail.setdefault("revision", 1)
                detail.setdefault("corrections", [])
                detail.setdefault("related_event_ids", [])
                detail.setdefault("related_relation_ids", [])
                details[event_id] = detail
                continue
            event = {
                "id": event_id,
                "lat": (context["geo"] or {}).get("lat"),
                "lng": (context["geo"] or {}).get("lng"),
                "cat": context["classification"]["category"],
            }
            details[event_id] = self._detail(event, context, previous_details.get(event_id))

        # Related events: two or more shared canonical countries.
        index: Dict[str, List[str]] = defaultdict(list)
        for event_id in wanted:
            countries = (
                contexts.get(event_id, {}).get("countries")
                or details.get(event_id, {}).get("countries")
                or []
            )
            for country in countries:
                if len(index[country]) < 400:
                    index[country].append(event_id)
        for event_id in wanted:
            scores: Counter = Counter()
            for country in (
                contexts.get(event_id, {}).get("countries")
                or details.get(event_id, {}).get("countries")
                or []
            ):
                for other in index.get(country, []):
                    if other != event_id:
                        scores[other] += 1
            details[event_id]["related_event_ids"] = [
                other for other, count in scores.most_common(4) if count >= 2
            ]

        # Related arcs: every arc stores the events that support it.
        for arc in arcs:
            arc_id = _text(arc.get("id"))
            for event_id in arc.get("event_ids") or []:
                if event_id in details and arc_id and len(details[event_id]["related_relation_ids"]) < 6:
                    details[event_id]["related_relation_ids"].append(arc_id)

        return details

    # ------------------------------------------------------------- persistence
    def _event_rows(self, events: List[Dict[str, Any]], contexts: Dict[str, Dict[str, Any]], wanted: set) -> List[Dict[str, Any]]:
        rows = []
        for event in events:
            if event["id"] not in wanted or event["id"] not in contexts:
                continue
            context = contexts[event["id"]]
            if context.get("historical"):
                row = dict(event)
                row.update(
                    {
                        "event_id": event["id"],
                        "title": _text(event.get("t")),
                        "status": _text(event.get("st")),
                        "category": _text(event.get("cat")),
                        "importance": event.get("imp"),
                        "location_name": event.get("loc"),
                        "geo_precision": event.get("gp"),
                        "countries": context.get("countries") or [],
                    }
                )
                rows.append(row)
                continue
            row = dict(event)
            row.update(
                {
                    "event_id": event["id"],
                    "title": context["title"],
                    "status": event["st"],
                    "category": event["cat"],
                    "severity": context["classification"]["severity"],
                    "importance": event["imp"],
                    "confidence": context["scoring"]["confidence"],
                    "location_name": event["loc"],
                    "geo_precision": event["gp"],
                    "countries": context["countries"],
                    "source_ids": sorted(
                        {_text(article.get("id")) for article in context["cluster"] if _text(article.get("id"))}
                    ),
                    "first_seen": context["first_seen"].isoformat(),
                    "last_updated": context["last_updated"].isoformat(),
                    "summary": context["summary"]["summary"],
                    "summary_method": context["summary"]["method"],
                    "source_sig": context["summary"]["source_sig"],
                    "social_buzz_score": context["social"]["social_buzz_score"],
                    "has_official_source": context["coverage"]["has_official_source"],
                    "article_count": len(context["cluster"]),
                    "source_count": context["coverage"]["source_count"],
                }
            )
            rows.append(row)
        return rows

    def _detail_rows(self, details: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for event_id, detail in details.items():
            row = dict(detail)
            row["event_id"] = event_id
            rows.append(row)
        return rows

    def _write_gold(
        self,
        events: List[Dict[str, Any]],
        arcs: List[Dict[str, Any]],
        snapshots: Dict[str, Dict[str, Any]],
        details: Dict[str, Dict[str, Any]],
        wanted: set,
        contexts: Dict[str, Dict[str, Any]],
    ) -> None:
        event_rows = self._event_rows(events, contexts, wanted)
        self.store.write("gold", "events", event_rows, self.run_id, self.partition_date)
        self.store.write("gold", "event_details", self._detail_rows(details), self.run_id, self.partition_date)
        self.store.write("gold", "arcs", arcs, self.run_id, self.partition_date)

        snapshot_rows = []
        for window, snapshot in snapshots.items():
            snapshot_rows.append(
                {
                    "window": window,
                    "ts": snapshot.get("ts"),
                    "n_events": snapshot.get("n", {}).get("e", 0),
                    "n_arcs": snapshot.get("n", {}).get("a", 0),
                    "payload": snapshot,
                }
            )
        self.store.write("gold", "snapshots", snapshot_rows, self.run_id, self.partition_date)

        stats = self.store.stats()
        logger.info("Parquet lake now holds %d table(s): %s", len(stats), stats)

    def _write_manifest(
        self,
        events: List[Dict[str, Any]],
        arcs: List[Dict[str, Any]],
        snapshots: Dict[str, Dict[str, Any]],
        details: Dict[str, Dict[str, Any]],
        source_stats: Dict[str, Dict[str, Any]],
        pull_counts: Dict[str, int],
        quality: Dict[str, Dict[str, Any]],
        pushed: bool,
        pruned: bool,
        replay: Optional[Dict[str, Any]] = None,
    ) -> None:
        path = self.serving_dir / "manifest.json"
        manifest: Dict[str, Any] = {}
        if path.exists():
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                manifest = {}
        manifest.update(
            {
                "run_id": self.run_id,
                "generated_at": self.now.isoformat(),
                "tier": os.getenv("PIPELINE_TIER", "manual").strip().lower() or "manual",
                "storage": {
                    "backend": "huggingface" if self.hf.enabled else "local-parquet",
                    "storage_type": self.hf.storage_type,
                    "repo": self.hf.repo_id or None,
                    "data_dir": str(self.data_dir),
                },
                "windows": {
                    window: {
                        "events": snapshot.get("n", {}).get("e", 0),
                        "arcs": snapshot.get("n", {}).get("a", 0),
                        "total_available": snapshot.get("n", {}).get("available")
                        if snapshot.get("n", {}).get("available") is not None
                        else snapshot.get("n", {}).get("total"),
                        "span_hours": snapshot.get("n", {}).get("span_hours"),
                        "available_from": snapshot.get("n", {}).get("available_from"),
                        "available_to": snapshot.get("n", {}).get("available_to"),
                        "span_complete": snapshot.get("n", {}).get("span_complete"),
                        "total_scope": snapshot.get("n", {}).get("total_scope"),
                        "top_n": True,
                        "generated_at": snapshot.get("ts"),
                    }
                    for window, snapshot in snapshots.items()
                },
                "counts": {
                    "events_total": len(events),
                    "details": len(details),
                    "arcs": len(arcs),
                    "snapshot_event_ids": len(
                        {event["id"] for snapshot in snapshots.values() for event in snapshot.get("events", [])}
                    ),
                },
                "sources": source_stats,
                "source_health": {
                    status: sum(1 for stats in source_stats.values() if stats.get("status") == status)
                    for status in ("ok", "partial", "empty", "skipped", "failed")
                },
                "hf_pull": pull_counts,
                "quality": quality,
                "serving": self._serving_checksums(),
                "replay": {
                    "frames": len(replay.get("frames") or []) if replay else 0,
                    "available_runs": replay.get("available_runs", 0) if replay else 0,
                    "from": (replay.get("frames") or [{}])[0].get("ts") if replay else None,
                    "to": (replay.get("frames") or [{}])[-1].get("ts") if replay else None,
                    "source_window": replay.get("source_window") if replay else None,
                },
                "hf_push": pushed,
                "pruned": pruned,
            }
        )
        self._write_json("manifest.json", manifest)

    def _serving_checksums(self) -> Dict[str, Any]:
        """Checksums let the API/operator verify the serving set as a unit."""
        names = [
            "world_1h.json",
            "world_24h.json",
            "world_7d.json",
            "world_30d.json",
            "event_details.json",
            "rewind.json",
            "search_index.sqlite3",
        ]
        files: Dict[str, str] = {}
        for name in names:
            path = self.serving_dir / name
            if not path.is_file():
                continue
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            files[name] = digest.hexdigest()
        combined = hashlib.sha256(
            "|".join(f"{name}:{digest}" for name, digest in sorted(files.items())).encode("utf-8")
        ).hexdigest()
        return {"run_id": self.run_id, "files": files, "digest": combined}

    def _write_json(self, filename: str, payload: Any) -> None:
        target = self.serving_dir / filename
        temporary = target.with_suffix(target.suffix + ".tmp")
        cleaned = _sanitise_nested(payload)
        temporary.write_text(
            json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
        )
        os.replace(temporary, target)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    flow = PipelineFlow()
    result = flow.run()
    logger.info(
        "Pipeline finished: %s events / %s arcs",
        result.get("n", {}).get("e"),
        result.get("n", {}).get("a"),
    )
    if flow.last_error is not None:
        raise SystemExit(1)
