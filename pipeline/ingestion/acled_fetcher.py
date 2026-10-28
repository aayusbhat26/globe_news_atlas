"""Optional ACLED conflict-event ingestion using the current OAuth API.

ACLED now issues 24-hour access tokens from a username/password (or refresh
token) exchange. The token is cached in-process; credentials and tokens are
never logged or sent to the frontend.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from pipeline.config import settings
from pipeline.ingestion.base_fetcher import BaseFetcher
from pipeline.ingestion.schema import make_raw_article

logger = logging.getLogger("pipeline.ingestion.acled")

TOKEN_URL = "https://acleddata.com/oauth/token"
API_URL = "https://acleddata.com/api/acled/read"

_TOKEN_CACHE: Dict[str, Any] = {"access_token": "", "refresh_token": "", "expires_at": 0.0}
_AUTH_BLOCKED_UNTIL = 0.0


class ACLEDFetcher(BaseFetcher):
    def __init__(self):
        super().__init__(name="acled", max_retries=1, circuit_break_seconds=3600)
        self.email = settings.acled_email
        self.password = settings.acled_password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0 (ACLED research)"})

    def _new_token(self, grant_type: str) -> Optional[str]:
        if grant_type == "refresh_token":
            payload = {
                "refresh_token": _TOKEN_CACHE.get("refresh_token", ""),
                "grant_type": "refresh_token",
                "client_id": "acled",
            }
        else:
            payload = {
                "username": self.email,
                "password": self.password,
                "grant_type": "password",
                "client_id": "acled",
                "scope": "authenticated",
            }
        try:
            response = self.session.post(
                TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=settings.request_timeout * 3,
            )
            if response.status_code in {400, 401}:
                global _AUTH_BLOCKED_UNTIL
                _AUTH_BLOCKED_UNTIL = time.time() + 3600
                try:
                    detail = response.json().get("error_description") or response.json().get("error")
                except Exception:
                    detail = "authentication rejected"
                logger.warning(
                    "ACLED OAuth rejected (%s). Check ACLED_EMAIL/ACLED_PASSWORD or account access.",
                    detail,
                )
                return None
            response.raise_for_status()
            body = response.json()
            access = str(body.get("access_token") or "")
            if not access:
                logger.warning("ACLED OAuth returned no access token.")
                return None
            _TOKEN_CACHE["access_token"] = access
            _TOKEN_CACHE["refresh_token"] = str(body.get("refresh_token") or _TOKEN_CACHE.get("refresh_token") or "")
            _TOKEN_CACHE["expires_at"] = time.time() + int(body.get("expires_in") or 86400)
            return access
        except Exception as exc:
            logger.warning("ACLED OAuth request failed: %s", type(exc).__name__)
            return None

    def _token(self) -> Optional[str]:
        if time.time() < _AUTH_BLOCKED_UNTIL:
            return None
        access = _TOKEN_CACHE.get("access_token")
        if access and float(_TOKEN_CACHE.get("expires_at") or 0) > time.time() + 90:
            return str(access)
        if _TOKEN_CACHE.get("refresh_token"):
            refreshed = self._new_token("refresh_token")
            if refreshed:
                return refreshed
        return self._new_token("password")

    def _invalidate_token(self) -> None:
        _TOKEN_CACHE["access_token"] = ""
        _TOKEN_CACHE["expires_at"] = 0.0

    def fetch(self) -> List[Dict[str, Any]]:
        self.begin_fetch()
        if not self.email or not self.password:
            logger.info("ACLED credentials not configured; skipping.")
            return self.finish_fetch([], skipped_reason="ACLED credentials are not configured")
        if self.is_circuit_open():
            return self.finish_fetch([], skipped_reason="circuit breaker open")

        token = self._token()
        if not token:
            return self.finish_fetch([], status="failed", error="ACLED OAuth token unavailable")

        since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        payload: Dict[str, Any] = {}
        for attempt in range(2):
            try:
                response = self.session.get(
                    API_URL,
                    params={
                        "_format": "json",
                        "limit": 250,
                        "event_date": since,
                        "event_date_where": ">=",
                    },
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    timeout=settings.request_timeout * 4,
                )
                if response.status_code == 401 and attempt == 0:
                    self._invalidate_token()
                    token = self._token()
                    if not token:
                        break
                    continue
                response.raise_for_status()
                payload = response.json()
                break
            except Exception as exc:
                logger.warning("ACLED fetch failed: %s", type(exc).__name__)
                if attempt == 1:
                    return self.finish_fetch(
                        [],
                        status="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )

        if not isinstance(payload, dict) or payload.get("status") not in (None, 200):
            logger.warning("ACLED returned an unexpected payload.")
            return self.finish_fetch([], status="failed", error="ACLED returned an unexpected payload")

        records: List[Dict[str, Any]] = []
        for event in payload.get("data", []) or []:
            event_id = str(event.get("event_id_cnty") or event.get("event_id") or "")
            country = event.get("country") or ""
            location = event.get("location") or event.get("admin1") or country
            event_type = event.get("event_type") or "Conflict event"
            if not event_id:
                continue
            try:
                lat = float(event.get("latitude"))
                lng = float(event.get("longitude"))
            except (TypeError, ValueError):
                lat = lng = None
            title = f"{event_type}: {location}, {country}".strip(", ")
            notes = event.get("notes") or event.get("sub_event_type") or ""
            category = "conflict"
            if event_type.lower() in {"protests", "riots"}:
                category = "protest"
            elif event_type.lower() == "strategic developments":
                category = "politics"
            records.append(
                make_raw_article(
                    source="acled",
                    source_id=event_id,
                    title=title,
                    url="",
                    outlet="ACLED",
                    domain="acleddata.com",
                    alignment="centre",
                    country=None,
                    language="en",
                    published_at=f"{event.get('event_date', '')}T00:00:00Z",
                    snippet=notes,
                    lat=lat,
                    lng=lng,
                    location_name=location,
                    geo_precision="city" if event.get("location") else "region",
                    category=category,
                    source_metadata={
                        "event_type": event_type,
                        "sub_event_type": event.get("sub_event_type"),
                        "actor1": event.get("actor1"),
                        "actor2": event.get("actor2"),
                        "fatalities": event.get("fatalities"),
                        "source": event.get("source"),
                        "country": country,
                    },
                    raw_payload={"event": event},
                )
            )

        logger.info("ACLED gathered %d events", len(records))
        return self.finish_fetch(records)
