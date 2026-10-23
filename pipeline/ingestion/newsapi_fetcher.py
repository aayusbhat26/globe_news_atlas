"""Optional NewsAPI ingestion (free developer key, 100 requests/day)."""
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import make_raw_article

logger = logging.getLogger("pipeline.ingestion.newsapi")


class NewsAPIFetcher(BaseFetcher):
    ENDPOINT = "https://newsapi.org/v2/top-headlines"

    def __init__(self):
        super().__init__(name="newsapi", max_retries=1, circuit_break_seconds=3600)
        self.api_key = settings.newsapi_key
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0"})
        self.usage_path = Path(settings.data_dir) / "source_usage.json"

    def _allow_request(self) -> bool:
        today = time.strftime("%Y-%m-%d")
        limit = max(1, settings.newsapi_daily_limit)
        try:
            payload = json.loads(self.usage_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if payload.get("date") != today:
            payload = {"date": today, "counts": {}}
        counts = payload.setdefault("counts", {})
        used = int(counts.get("newsapi", 0))
        if used >= limit:
            logger.info("NewsAPI daily budget reached (%d/%d); skipping this run.", used, limit)
            return False
        counts["newsapi"] = used + 1
        try:
            self.usage_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.usage_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, self.usage_path)
        except Exception:
            pass
        return True

    def fetch(self) -> List[Dict[str, Any]]:
        if not self.api_key:
            logger.info("NewsAPI key not configured; skipping.")
            return []
        if self.is_circuit_open():
            return []
        if not self._allow_request():
            return []

        try:
            response = self.session.get(
                self.ENDPOINT,
                params={
                    "category": "general",
                    "language": "en",
                    "pageSize": 50,
                    "apiKey": self.api_key,
                },
                timeout=settings.request_timeout * 2,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("NewsAPI fetch failed: %s", exc)
            self.record_failure()
            return []

        records: List[Dict[str, Any]] = []
        seen: set = set()
        for article in payload.get("articles", []):
            title = (article.get("title") or "").strip()
            url = (article.get("url") or "").strip()
            if not title or not url or title == "[Removed]" or url in seen:
                continue
            seen.add(url)
            source = article.get("source") or {}
            outlet = source.get("name", "")
            domain = urlparse(url).netloc
            snippet = article.get("description") or article.get("content") or ""
            records.append(
                make_raw_article(
                    source="newsapi",
                    source_id=url,
                    title=title,
                    url=url,
                    outlet=outlet,
                    domain=domain,
                    alignment="unrated",
                    country=None,
                    language="en",
                    author=article.get("author", ""),
                    published_at=article.get("publishedAt"),
                    snippet=snippet,
                    category=None,
                    source_metadata={
                        "image_url": article.get("urlToImage"),
                        "source_id": source.get("id"),
                    },
                    raw_payload={
                        "source": source,
                        "author": article.get("author"),
                        "description": article.get("description"),
                    },
                )
            )

        if records:
            self.record_success()
        logger.info("NewsAPI gathered %d articles", len(records))
        return records
