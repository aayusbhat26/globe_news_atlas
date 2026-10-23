"""GDELT 2.0 ingestion.

Two distinct feeds are used:

* ``GDELTFetcher`` reads the 15-minute event export (CAMEO-coded events with
  ActionGeo coordinates). These are event records, not outlet articles, and
  are labelled as such in the data.
* ``GDELTDocFetcher`` queries the DOC 2.0 article API for real news URLs.
"""
import csv
import io
import logging
import math
import time
import zipfile
from collections import Counter
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import canonicalize_url, make_raw_article, parse_datetime, stable_id
from pipeline.transforms.country_codes import canonical_country

logger = logging.getLogger("pipeline.ingestion.gdelt")


class GDELTRateLimited(Exception):
    """Raised when GDELT DOC keeps returning 429 for the current client."""

EVENT_PHRASES = {
    "01": ("issues a public statement about", "issued a public statement"),
    "02": ("appeals for", "issued an appeal"),
    "03": ("signals intent to cooperate with", "signalled intent to cooperate"),
    "04": ("consults with", "held consultations"),
    "05": ("cooperates diplomatically with", "engaged in diplomatic cooperation"),
    "06": ("cooperates materially with", "engaged in material cooperation"),
    "07": ("provides aid to", "provided aid"),
    "08": ("yields to", "yielded"),
    "09": ("investigates", "launched an investigation"),
    "10": ("demands action from", "issued demands"),
    "11": ("disapproves of", "expressed disapproval"),
    "12": ("rejects", "rejected an action"),
    "13": ("threatens", "issued a threat"),
    "14": ("protest against", "protested"),
    "15": ("shows force posture toward", "showed force posture"),
    "16": ("reduces relations with", "reduced relations"),
    "17": ("coerces", "used coercion"),
    "18": ("assaults", "carried out an assault"),
    "19": ("fights", "engaged in fighting"),
    "20": ("uses unconventional mass violence against", "used mass violence"),
}

CONFLICT_CODES = {"18", "19", "20"}
PROTEST_CODES = {"14"}
DIPLOMACY_CODES = {"01", "02", "03", "04", "05", "06", "07", "08", "16"}

ACRONYMS = {
    "NATO": "NATO",
    "UN": "UN",
    "UNITED NATIONS": "United Nations",
    "EU": "EU",
    "EUROPEAN UNION": "European Union",
    "US": "US",
    "USA": "US",
    "UNITED STATES": "United States",
    "UK": "UK",
    "UNITED KINGDOM": "United Kingdom",
    "ISIS": "ISIS",
    "ISIL": "ISIL",
    "WHO": "WHO",
    "IMF": "IMF",
}


def _pretty_actor(value: str) -> str:
    text = (value or "").strip().strip('"')
    if not text or text.upper() == "NONE":
        return ""
    upper = text.upper()
    if upper in ACRONYMS:
        return ACRONYMS[upper]
    return " ".join(word.capitalize() for word in text.split())


def _safe_int(row: List[str], index: int, default: int = 0) -> int:
    try:
        return int(float(row[index]))
    except (IndexError, TypeError, ValueError):
        return default


def _safe_float(row: List[str], index: int, default: float = 0.0) -> float:
    try:
        return float(row[index])
    except (IndexError, TypeError, ValueError):
        return default


def _category(root_code: str) -> str:
    if root_code in CONFLICT_CODES:
        return "conflict"
    if root_code in PROTEST_CODES:
        return "protest"
    if root_code in DIPLOMACY_CODES:
        return "diplomacy"
    return "politics"


class GDELTFetcher(BaseFetcher):
    LAST_UPDATE_URL = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"

    def __init__(self, max_events: Optional[int] = None, session: Optional[requests.Session] = None):
        super().__init__(name="gdelt_events")
        self.max_events = max_events or settings.gdelt_top_events
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0 (GDELT event ingestion)"})

    def _export_url(self) -> Optional[str]:
        resp = self.session.get(self.LAST_UPDATE_URL, timeout=settings.request_timeout * 2)
        resp.raise_for_status()
        for line in resp.text.splitlines():
            if "export.CSV.zip" in line:
                return line.split()[-1].replace("http://", "https://")
        return None

    def fetch(self) -> List[Dict[str, Any]]:
        if self.is_circuit_open():
            logger.info("GDELT event fetch skipped: circuit breaker is open.")
            return []
        try:
            url = self._export_url()
            if not url:
                logger.warning("GDELT lastupdate did not contain an export file.")
                self.record_failure()
                return []

            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                name = next((n for n in archive.namelist() if n.endswith(".CSV") or n.endswith(".csv")), None)
                if not name:
                    return []
                with archive.open(name) as handle:
                    text = handle.read().decode("utf-8", errors="replace")

            candidates: List[Dict[str, Any]] = []
            reader = csv.reader(io.StringIO(text), delimiter="\t")
            for row in reader:
                record = self._parse_row(row)
                if record:
                    candidates.append(record)

            unique: Dict[tuple, Dict[str, Any]] = {}
            for record in candidates:
                metadata = record["source_metadata"]
                key = (
                    metadata.get("actor1_name"),
                    metadata.get("actor2_name"),
                    metadata.get("event_code"),
                    metadata.get("action_country"),
                    round(record.get("lat") or 0, 1),
                    round(record.get("lng") or 0, 1),
                )
                existing = unique.get(key)
                if not existing or metadata.get("num_articles", 0) > existing["source_metadata"].get("num_articles", 0):
                    unique[key] = record

            def rank(item: Dict[str, Any]) -> float:
                meta = item["source_metadata"]
                return (
                    meta.get("num_articles", 0) * 2
                    + meta.get("num_sources", 0) * 3
                    + math.log1p(meta.get("num_mentions", 0))
                )

            ranked = sorted(unique.values(), key=rank, reverse=True)[: self.max_events]
            self.record_success()
            logger.info(
                "GDELT events: %d parsed, %d unique, %d kept from %s",
                len(candidates),
                len(unique),
                len(ranked),
                url.rsplit("/", 1)[-1],
            )
            return ranked
        except Exception as exc:
            logger.warning("GDELT event fetch failed: %s", exc)
            self.record_failure()
            return []

    def _parse_row(self, row: List[str]) -> Optional[Dict[str, Any]]:
        # GDELT 2.0 export layout (61 tab-separated columns, 0-based indices):
        # 26 EventCode, 28 EventRootCode, 29 QuadClass, 31-34 mention metrics,
        # 51 ActionGeo_Type, 52 ActionGeo_FullName, 53 country FIPS,
        # 56/57 ActionGeo lat/lng, 59 DATEADDED, 60 SOURCEURL.
        if len(row) < 61:
            return None
        try:
            lat = float(row[56])
            lng = float(row[57])
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (abs(lat) < 0.001 and abs(lng) < 0.001):
            return None

        root_code = (row[28] or "").strip()
        if not root_code:
            return None
        actor1 = _pretty_actor(row[6])
        actor2 = _pretty_actor(row[16])
        actor1_country = canonical_country(row[7])
        actor2_country = canonical_country(row[17])
        geo_name = (row[52] or "").strip()
        action_country = (row[53] or "").strip()
        event_code = (row[26] or "").strip()
        phrase, intransitive = EVENT_PHRASES.get(root_code, ("reports developments involving", "reported developments"))

        if actor1 and actor2:
            title = f"{actor1} {phrase} {actor2}"
        elif actor1:
            title = f"{actor1}: {intransitive}"
        elif geo_name:
            title = f"{intransitive.capitalize()} in {geo_name.split(',')[0].strip()}"
        else:
            return None

        source_url = (row[60] or "").strip()
        event_id = (row[0] or "").strip()
        date_added = parse_datetime((row[59] or "").strip())

        geo_type = (row[51] or "").strip()
        precision = {"1": "country", "2": "region", "3": "city", "4": "city", "5": "region"}.get(geo_type, "region")

        metadata = {
            "actor1_name": actor1,
            "actor2_name": actor2,
            "actor1_code": row[5],
            "actor2_code": row[15],
            "actor1_country": actor1_country,
            "actor2_country": actor2_country,
            "event_code": event_code,
            "event_root_code": root_code,
            "quad_class": _safe_int(row, 29),
            "goldstein": _safe_float(row, 30),
            "num_mentions": _safe_int(row, 31),
            "num_sources": _safe_int(row, 32),
            "num_articles": _safe_int(row, 33),
            "avg_tone": _safe_float(row, 34),
            "action_geo_name": geo_name,
            "action_country_fips": action_country,
            "is_event_record": True,
        }

        snippet = f"GDELT CAMEO {event_code or root_code} event"
        if actor1 or actor2:
            snippet += f": {actor1 or 'Unknown actor'} → {actor2 or 'location'}"
        if geo_name:
            snippet += f" in {geo_name}"
        snippet += f" ({metadata['num_articles']} articles, {metadata['num_sources']} sources)."

        return make_raw_article(
            source="gdelt_events",
            source_id=event_id or stable_id("gdelt", row[0], row[58], title),
            title=title,
            url=source_url,
            outlet="GDELT event record",
            alignment="unrated",
            country=None,
            language="en",
            published_at=date_added,
            snippet=snippet,
            lat=lat,
            lng=lng,
            location_name=geo_name or None,
            geo_precision=precision,
            category=_category(root_code),
            source_metadata=metadata,
            raw_payload={"global_event_id": event_id, "source_url": source_url},
        )


class GDELTDocFetcher(BaseFetcher):
    API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
    MIN_INTERVAL = 6.0

    def __init__(self, queries: Optional[List[str]] = None, session: Optional[requests.Session] = None):
        super().__init__(name="gdelt_doc", max_retries=2, circuit_break_seconds=600)
        self.queries = queries or settings.gdelt_doc_queries
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0 (GDELT DOC ingestion)"})
        self._last_request = 0.0

    def _throttle(self) -> None:
        wait = self.MIN_INTERVAL - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _query(self, query: str) -> Dict[str, Any]:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(settings.gdelt_doc_max_records, 250),
            "timespan": settings.gdelt_doc_timespan,
            "sort": "hybridrel",
        }
        last_error: Optional[Exception] = None
        rate_limited = False
        for attempt in range(2):
            self._throttle()
            try:
                response = self.session.get(
                    self.API_URL,
                    params=params,
                    timeout=settings.request_timeout * 2,
                )
                self._last_request = time.monotonic()
                if response.status_code == 429:
                    wait = float(response.headers.get("Retry-After") or 10)
                    logger.info("GDELT DOC rate-limited; waiting %.0fs", wait)
                    time.sleep(wait)
                    rate_limited = True
                    last_error = requests.HTTPError("429 rate limited")
                    continue
                response.raise_for_status()
                if "application/json" not in response.headers.get("Content-Type", ""):
                    raise ValueError("GDELT DOC returned non-JSON")
                return response.json()
            except Exception as exc:
                last_error = exc
        if rate_limited:
            raise GDELTRateLimited("GDELT DOC is rate-limiting this client")
        if last_error:
            raise last_error
        return {}

    def fetch(self) -> List[Dict[str, Any]]:
        if self.is_circuit_open():
            logger.info("GDELT DOC fetch skipped: circuit breaker is open.")
            return []

        seen: set = set()
        records: List[Dict[str, Any]] = []
        failures = 0
        consecutive_failures = 0
        for query in self.queries:
            try:
                payload = self._query(query)
            except GDELTRateLimited:
                logger.warning("GDELT DOC is rate-limiting this client; stopping DOC queries for this run.")
                failures += 1
                break
            except Exception as exc:
                logger.warning("GDELT DOC query %r failed: %s", query, exc)
                failures += 1
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    logger.warning("GDELT DOC is rate-limiting; stopping DOC queries for this run.")
                    break
                continue
            consecutive_failures = 0

            for article in payload.get("articles", []):
                url = (article.get("url") or "").strip()
                title = (article.get("title") or "").strip()
                if not url or not title:
                    continue
                canonical = canonicalize_url(url)
                if canonical in seen:
                    continue
                seen.add(canonical)
                domain = (article.get("domain") or urlparse(url).netloc).lower()
                records.append(
                    make_raw_article(
                        source="gdelt_doc",
                        source_id=canonical,
                        title=title,
                        url=url,
                        outlet=domain,
                        domain=domain,
                        language=(article.get("language") or "en").lower(),
                        published_at=article.get("seendate"),
                        country=None,
                        snippet=title,
                        category=None,
                        source_metadata={
                            "query": query,
                            "source_country": article.get("sourcecountry"),
                            "domain": domain,
                        },
                        raw_payload=article,
                    )
                )
                if len(records) >= settings.gdelt_doc_max_articles:
                    break
            if len(records) >= settings.gdelt_doc_max_articles:
                break

        if records:
            self.record_success()
        elif failures:
            self.record_failure()
        else:
            self.record_success()
        logger.info("GDELT DOC gathered %d articles (%d query failures)", len(records), failures)
        return records
