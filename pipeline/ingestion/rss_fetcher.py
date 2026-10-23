"""Curated RSS ingestion with per-outlet metadata from seeds/outlets.json."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import canonicalize_url, clean_text, make_raw_article

try:
    import feedparser
except ImportError:  # pragma: no cover - dependency is declared in requirements
    feedparser = None

logger = logging.getLogger("pipeline.ingestion.rss")

USER_AGENT = (
    "Mozilla/5.0 (compatible; GlobeNewsAtlas/1.0; +https://github.com/aayusbhat26/project_1) "
    "feedparser"
)


class RSSFetcher(BaseFetcher):
    """Fetches curated international feeds, keeping outlet alignment metadata."""

    def __init__(self, seeds_file: Optional[Path] = None, max_workers: int = 8):
        super().__init__(name="rss", max_retries=3, circuit_break_seconds=900)
        self.seeds_file = seeds_file or Path(__file__).resolve().parent.parent.parent / "seeds" / "outlets.json"
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})

    def _load_outlets(self) -> List[Dict[str, Any]]:
        if not self.seeds_file.exists():
            logger.warning("Seeds file not found: %s", self.seeds_file)
            return []
        with open(self.seeds_file, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        outlets = []
        seen = set()
        for outlet in raw if isinstance(raw, list) else []:
            outlet_id = str(outlet.get("id") or "").strip()
            feed_url = str(outlet.get("feed_url") or "").strip()
            if not outlet_id or not feed_url or outlet_id in seen:
                continue
            seen.add(outlet_id)
            outlets.append(outlet)
        return outlets

    def _fetch_outlet(self, outlet: Dict[str, Any]) -> List[Dict[str, Any]]:
        feed_url = outlet["feed_url"]
        response = self.session.get(feed_url, timeout=settings.request_timeout, allow_redirects=True)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        records: List[Dict[str, Any]] = []
        is_paywalled = bool(outlet.get("paywall", False))
        for entry in feed.entries[: settings.rss_max_items]:
            title = clean_text(entry.get("title", ""), 400)
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            raw_summary = entry.get("summary") or entry.get("description") or ""
            if not raw_summary and entry.get("content"):
                raw_summary = entry["content"][0].get("value", "")
            summary = clean_text(raw_summary, 300 if is_paywalled else 1200)
            if is_paywalled and summary:
                summary = f"[Headline only] {summary[:300]}"
            published = entry.get("published") or entry.get("updated")
            if not published:
                parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                if parsed:
                    published = datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            tags = [tag.get("term", "") for tag in entry.get("tags", []) if tag.get("term")]
            records.append(
                make_raw_article(
                    source="rss",
                    source_id=(entry.get("id") or link),
                    title=title,
                    url=link,
                    outlet=outlet.get("name", outlet.get("id", "")),
                    outlet_id=outlet.get("id", ""),
                    domain=outlet.get("domain", ""),
                    alignment=outlet.get("alignment", "unrated"),
                    country=outlet.get("country"),
                    language=outlet.get("language", "en"),
                    author=entry.get("author", ""),
                    published_at=published,
                    snippet=summary,
                    content="" if is_paywalled else summary,
                    is_paywalled=is_paywalled,
                    category=outlet.get("category"),
                    source_metadata={
                        "feed_url": feed_url,
                        "feed_title": feed.feed.get("title", ""),
                        "tags": tags,
                        "reliability_score": outlet.get("reliability_score"),
                        "rating_source": outlet.get("rating_source"),
                        "paywall": is_paywalled,
                    },
                    raw_payload={
                        "id": entry.get("id"),
                        "link": link,
                        "author": entry.get("author"),
                        "published": published,
                        "tags": tags,
                    },
                )
            )
        return records

    def fetch(self) -> List[Dict[str, Any]]:
        if self.is_circuit_open():
            logger.info("RSS fetch skipped: circuit breaker open.")
            return []
        if not feedparser:
            logger.warning("feedparser is not installed; skipping RSS crawl.")
            return []

        outlets = self._load_outlets()
        if settings.rss_max_outlets > 0:
            outlets = outlets[: settings.rss_max_outlets]
        if not outlets:
            return []

        records: List[Dict[str, Any]] = []
        seen_urls: set = set()
        succeeded = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=max(1, self.max_workers)) as pool:
            futures = {pool.submit(self._fetch_outlet, outlet): outlet for outlet in outlets}
            for future in as_completed(futures):
                outlet = futures[future]
                try:
                    items = future.result()
                    succeeded += 1
                except Exception as exc:
                    failed += 1
                    logger.warning("RSS feed for %s failed: %s", outlet.get("id"), exc)
                    continue
                for item in items:
                    key = item["canonical_url"] or item["title"].lower()
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    records.append(item)

        records.sort(key=lambda r: r["published_at"] or "", reverse=True)
        if succeeded:
            self.record_success()
        else:
            self.record_failure()
        logger.info("RSS: %d articles from %d/%d feeds (%d failed)", len(records), succeeded, len(outlets), failed)
        return records
