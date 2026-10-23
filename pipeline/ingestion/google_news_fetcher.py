"""Google News RSS search ingestion.

Google News provides free, key-less access to recent and multi-day headlines.
The RSS link is an aggregator redirect; the original outlet is recorded from the
entry's ``<source>`` element and title suffix.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import quote_plus, urlparse

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import canonicalize_url, clean_text, make_raw_article

try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None

logger = logging.getLogger("pipeline.ingestion.google_news")

# (query, edition, language)
DEFAULT_QUERIES: List[Tuple[str, str, str]] = [
    ("top stories when:1d", "US", "en"),
    ("world when:1d", "US", "en"),
    ("geopolitics when:2d", "US", "en"),
    ("conflict OR ceasefire when:2d", "US", "en"),
    ("election OR parliament when:2d", "US", "en"),
    ("protest OR unrest when:2d", "US", "en"),
    ("economy OR markets when:1d", "US", "en"),
    ("climate OR earthquake OR flood when:2d", "US", "en"),
    ("United Nations when:2d", "US", "en"),
    ("India when:7d", "IN", "en"),
    ("China when:7d", "US", "en"),
    ("Ukraine war when:7d", "US", "en"),
    ("Middle East when:7d", "US", "en"),
    ("Bangladesh when:2d", "US", "en"),
    ("Saudi Arabia when:2d", "US", "en"),
    ("South Asia when:3d", "IN", "en"),
    ("human rights OR death penalty when:3d", "US", "en"),
    ("Africa when:7d", "US", "en"),
    ("Latin America when:7d", "US", "en"),
    ("Southeast Asia when:7d", "US", "en"),
    ("Europe when:7d", "US", "en"),
    ("United States politics when:7d", "US", "en"),
]

USER_AGENT = "Mozilla/5.0 (compatible; GlobeNewsAtlas/1.0)"


class GoogleNewsFetcher(BaseFetcher):
    BASE_URL = "https://news.google.com/rss/search"

    def __init__(self, queries: List[Tuple[str, str, str]] = None, max_workers: int = 4):
        super().__init__(name="google_news")
        self.queries = queries or DEFAULT_QUERIES
        self.max_workers = max_workers
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/rss+xml, */*"})

    def _fetch_query(self, item: Tuple[str, str, str]) -> List[Dict[str, Any]]:
        query, edition, language = item
        url = (
            f"{self.BASE_URL}?q={quote_plus(query)}"
            f"&hl={language}-{edition}&gl={edition}&ceid={edition}:{language}"
        )
        response = self.session.get(url, timeout=settings.request_timeout, allow_redirects=True)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        records: List[Dict[str, Any]] = []
        for entry in feed.entries[: settings.google_news_max_items]:
            title = clean_text(entry.get("title", ""), 400)
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            outlet = ""
            outlet_href = ""
            source = entry.get("source")
            if source:
                outlet = clean_text(source.get("title", ""), 120)
                outlet_href = source.get("href", "")
            clean_title = title
            if " - " in title:
                head, suffix = title.rsplit(" - ", 1)
                if suffix and (not outlet or suffix.lower() == outlet.lower()):
                    clean_title = head
                    outlet = suffix
            published = entry.get("published") or entry.get("updated")
            if not published:
                parsed = entry.get("published_parsed")
                if parsed:
                    published = datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()
            records.append(
                make_raw_article(
                    source="google_news",
                    source_id=link,
                    title=clean_title,
                    url=link,
                    outlet=outlet,
                    domain=urlparse(outlet_href).netloc if outlet_href else "",
                    alignment="unrated",
                    country=None,
                    language=language.lower(),
                    published_at=published,
                    snippet=entry.get("summary", ""),
                    category=None,
                    source_metadata={
                        "query": query,
                        "edition": edition,
                        "aggregator": "google_news",
                        "outlet_href": outlet_href,
                    },
                    raw_payload={"title": title, "link": link, "published": published},
                )
            )
        return records

    def fetch(self) -> List[Dict[str, Any]]:
        if self.is_circuit_open():
            logger.info("Google News fetch skipped: circuit breaker open.")
            return []
        if not feedparser:
            logger.warning("feedparser is not installed; skipping Google News crawl.")
            return []

        records: List[Dict[str, Any]] = []
        seen: set = set()
        succeeded = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=max(1, self.max_workers)) as pool:
            futures = {pool.submit(self._fetch_query, item): item for item in self.queries}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    items = future.result()
                    succeeded += 1
                except Exception as exc:
                    failed += 1
                    logger.warning("Google News query %r failed: %s", item[0], exc)
                    continue
                for record in items:
                    key = record["canonical_url"] or record["title"].lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    records.append(record)

        records.sort(key=lambda r: r["published_at"] or "", reverse=True)
        if succeeded:
            self.record_success()
        else:
            self.record_failure()
        logger.info("Google News: %d articles from %d queries (%d failed)", len(records), succeeded, failed)
        return records
