"""Bluesky public search ingestion (no account or API key required)."""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import make_raw_social

logger = logging.getLogger("pipeline.ingestion.bluesky")

QUERIES = [
    "geopolitics",
    "breaking news",
    "election",
    "protest",
    "earthquake",
    "climate",
    "conflict",
    "United Nations",
]


class BlueskyFetcher(BaseFetcher):
    # public.api.bsky.app now returns 403 for unauthenticated searches; the
    # api.bsky.app AppView still serves public search without credentials.
    SEARCH_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"

    def __init__(self):
        super().__init__(name="bluesky", max_retries=2, circuit_break_seconds=900)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0 (public Bluesky search)"})

    def _search(self, query: str, since: str) -> List[Dict[str, Any]]:
        params = {
            "q": query,
            "limit": 25,
            "sort": "latest",
            "since": since,
        }
        response = self.session.get(self.SEARCH_URL, params=params, timeout=settings.request_timeout * 2)
        response.raise_for_status()
        return response.json().get("posts", [])

    def fetch(self) -> List[Dict[str, Any]]:
        self.begin_fetch()
        if self.is_circuit_open():
            logger.info("Bluesky fetch skipped: circuit breaker open.")
            return self.finish_fetch([], skipped_reason="circuit breaker open")

        since = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat().replace("+00:00", "Z")
        records: List[Dict[str, Any]] = []
        seen: set = set()
        failures = 0
        feed_errors: Dict[str, str] = {}

        for query in QUERIES:
            try:
                posts = self._search(query, since)
            except Exception as exc:
                failures += 1
                feed_errors[query] = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("Bluesky search %r failed: %s", query, exc)
                continue
            for post in posts:
                uri = post.get("uri", "")
                if not uri or uri in seen:
                    continue
                text = (post.get("record", {}).get("text") or "").strip()
                if len(text) < 40:
                    continue
                author = post.get("author", {})
                handle = author.get("handle", "")
                rkey = uri.rsplit("/", 1)[-1]
                if not handle or not rkey:
                    continue
                seen.add(uri)
                embed = post.get("embed", {}) or {}
                external = embed.get("external", {}) or {}
                metadata = {
                    "did": author.get("did", ""),
                    "handle": handle,
                    "uri": uri,
                    "query": query,
                    "repost_count": post.get("repostCount", 0),
                    "quote_count": post.get("quoteCount", 0),
                    "link_url": external.get("uri", ""),
                    "link_title": external.get("title", ""),
                    "langs": post.get("record", {}).get("langs", []),
                }
                records.append(
                    make_raw_social(
                        source="bluesky",
                        source_id=uri,
                        text=text,
                        url=f"https://bsky.app/profile/{handle}/post/{rkey}",
                        author=handle,
                        community="bluesky",
                        score=int(post.get("likeCount", 0)) + 2 * int(post.get("repostCount", 0)),
                        comments=int(post.get("replyCount", 0)),
                        created_at=post.get("record", {}).get("createdAt") or post.get("indexedAt"),
                        matched_title=text[:280],
                        metadata=metadata,
                    )
                )
            time.sleep(0.4)

        logger.info("Bluesky gathered %d posts", len(records))
        if failures == len(QUERIES):
            return self.finish_fetch(
                records,
                status="failed",
                error="all Bluesky searches failed",
                feed_errors=feed_errors,
            )
        if failures:
            return self.finish_fetch(records, status="partial", feed_errors=feed_errors)
        return self.finish_fetch(records)
