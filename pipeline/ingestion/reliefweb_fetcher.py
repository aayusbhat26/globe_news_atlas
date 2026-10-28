"""ReliefWeb humanitarian report ingestion (free API, v2 requires an appname)."""
import logging
import os
from typing import Any, Dict, List

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import clean_text, make_raw_article

logger = logging.getLogger("pipeline.ingestion.reliefweb")

API_URL = "https://api.reliefweb.int/v2/reports"
FIELDS = [
    "title",
    "url",
    "date.created",
    "source.shortname",
    "source.name",
    "country.name",
    "disaster_type.name",
    "body",
]


class ReliefWebFetcher(BaseFetcher):
    def __init__(self):
        super().__init__(name="reliefweb")
        self.appname = os.getenv("RELIEFWEB_APPNAME", "").strip()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0 (ReliefWeb API)"})

    def fetch(self) -> List[Dict[str, Any]]:
        self.begin_fetch()
        if self.is_circuit_open():
            logger.info("ReliefWeb fetch skipped: circuit breaker open.")
            return self.finish_fetch([], skipped_reason="circuit breaker open")
        if not self.appname:
            logger.info("ReliefWeb skipped: RELIEFWEB_APPNAME is not configured.")
            return self.finish_fetch([], skipped_reason="RELIEFWEB_APPNAME is not configured")
        payload = {
            "appname": self.appname,
            "profile": "list",
            "preset": "latest",
            "limit": 60,
            "fields": {"include": FIELDS},
        }
        try:
            response = self.session.post(
                API_URL,
                params={"appname": self.appname},
                json=payload,
                timeout=settings.request_timeout * 2,
            )
            response.raise_for_status()
            data = response.json().get("data", [])
        except Exception as exc:
            logger.warning("ReliefWeb fetch failed: %s", exc)
            return self.finish_fetch([], status="failed", error=f"{type(exc).__name__}: {exc}")

        records: List[Dict[str, Any]] = []
        for item in data:
            fields = item.get("fields") or {}
            title = clean_text(fields.get("title", ""), 400)
            url = fields.get("url", "")
            if not title or not url:
                continue
            countries = [country.get("name", "") for country in fields.get("country", []) if country.get("name")]
            sources = [source.get("shortname") or source.get("name", "") for source in fields.get("source", [])]
            disasters = [d.get("name", "") for d in fields.get("disaster_type", []) if d.get("name")]
            body = clean_text(fields.get("body", ""), 1500)
            records.append(
                make_raw_article(
                    source="reliefweb",
                    source_id=str(item.get("id", url)),
                    title=title,
                    url=url,
                    outlet=", ".join(filter(None, sources)) or "ReliefWeb",
                    domain="reliefweb.int",
                    alignment="centre",
                    country=None,
                    language="en",
                    published_at=(fields.get("date") or {}).get("created"),
                    snippet=body or title,
                    location_name=", ".join(countries) or None,
                    geo_precision="country" if countries else None,
                    category="disaster" if disasters else "humanitarian",
                    source_metadata={
                        "countries": countries,
                        "sources": sources,
                        "disaster_types": disasters,
                        "report_id": item.get("id"),
                    },
                    raw_payload={"title": title, "body": body[:800]},
                )
            )

        logger.info("ReliefWeb gathered %d reports", len(records))
        return self.finish_fetch(records)
