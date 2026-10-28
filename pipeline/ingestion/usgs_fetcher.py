"""USGS earthquake hazard feed ingestion (GeoJSON, no key required)."""
import logging
from typing import Any, Dict, List

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import make_raw_article

logger = logging.getLogger("pipeline.ingestion.usgs")

FEEDS = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
)


class USGSFetcher(BaseFetcher):
    def __init__(self):
        super().__init__(name="usgs")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0 (USGS earthquake feed)"})

    def fetch(self) -> List[Dict[str, Any]]:
        self.begin_fetch()
        if self.is_circuit_open():
            logger.info("USGS fetch skipped: circuit breaker open.")
            return self.finish_fetch([], skipped_reason="circuit breaker open")

        records: List[Dict[str, Any]] = []
        seen: set = set()
        succeeded = 0
        feed_errors: Dict[str, str] = {}
        for feed_url in FEEDS:
            try:
                response = self.session.get(feed_url, timeout=settings.request_timeout * 2)
                response.raise_for_status()
                features = response.json().get("features", [])
                succeeded += 1
            except Exception as exc:
                logger.warning("USGS feed failed (%s): %s", feed_url, exc)
                feed_errors[feed_url] = f"{type(exc).__name__}: {exc}"[:200]
                continue

            for feature in features:
                props = feature.get("properties") or {}
                if props.get("type") not in (None, "earthquake"):
                    continue
                quake_id = feature.get("id") or props.get("code", "")
                if not quake_id or quake_id in seen:
                    continue
                coords = (feature.get("geometry") or {}).get("coordinates") or []
                if len(coords) < 2:
                    continue
                lng, lat = coords[0], coords[1]
                depth = coords[2] if len(coords) > 2 else None
                magnitude = props.get("mag")
                place = props.get("place") or props.get("title") or "Unknown location"
                if magnitude is None:
                    continue
                seen.add(quake_id)
                title = props.get("title") or f"M{magnitude:.1f} earthquake - {place}"
                alert = props.get("alert")
                tsunami = props.get("tsunami")
                snippet = f"Magnitude {magnitude} earthquake near {place}."
                if depth is not None:
                    snippet += f" Depth {depth:.1f} km."
                if alert:
                    snippet += f" USGS alert level: {alert.upper()}."
                if tsunami:
                    snippet += " Tsunami advisory issued."
                records.append(
                    make_raw_article(
                        source="usgs",
                        source_id=quake_id,
                        title=title,
                        url=props.get("url", ""),
                        outlet="USGS",
                        domain="earthquake.usgs.gov",
                        alignment="centre",
                        country=None,
                        language="en",
                        published_at=props.get("time"),
                        snippet=snippet,
                        lat=float(lat),
                        lng=float(lng),
                        location_name=place,
                        geo_precision="city" if " of " in place else "region",
                        category="disaster",
                        source_metadata={
                            "magnitude": magnitude,
                            "depth_km": depth,
                            "alert": alert,
                            "tsunami": tsunami,
                            "felt": props.get("felt"),
                            "significance": props.get("sig"),
                            "status": props.get("status"),
                            "usgs_event_id": quake_id,
                        },
                        raw_payload={"properties": props, "coordinates": coords},
                    )
                )

        records.sort(key=lambda r: r["published_at"] or "", reverse=True)
        logger.info("USGS gathered %d earthquakes", len(records))
        if feed_errors and succeeded:
            return self.finish_fetch(records, status="partial", feed_errors=feed_errors)
        if feed_errors and not succeeded:
            return self.finish_fetch(
                records,
                status="failed",
                error="all USGS feeds failed",
                feed_errors=feed_errors,
            )
        return self.finish_fetch(records)
