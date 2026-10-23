"""Honest geocoding: explicit coordinates, offline gazetteer, optional remote lookup.

There is deliberately no hash-to-hub fallback. When an article cannot be tied to
a real place it stays unresolved rather than being plotted in a random city.
"""
import logging
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional

import requests

from pipeline.transforms.country_codes import canonical_country
from pipeline.transforms.world_geodata import DEMONYM_MAP, WORLD_LOCATIONS

logger = logging.getLogger("pipeline.transforms.geocoder")

DISPUTED_LOCATIONS = {
    "kashmir": {"lat": 34.0837, "lng": 74.7973, "precision": "region", "disputed": "Kashmir Region"},
    "crimea": {"lat": 44.9521, "lng": 34.1024, "precision": "region", "disputed": "Crimea Peninsula"},
    "golan heights": {"lat": 33.125, "lng": 35.805, "precision": "region", "disputed": "Golan Heights"},
    "western sahara": {"lat": 24.2155, "lng": -12.8858, "precision": "region", "disputed": "Western Sahara"},
    "taiwan strait": {"lat": 24.5, "lng": 119.5, "precision": "region", "disputed": "Taiwan Strait"},
    "spratly islands": {"lat": 9.88, "lng": 114.99, "precision": "region", "disputed": "Spratly Islands"},
    "donbas": {"lat": 48.0, "lng": 37.8, "precision": "region", "disputed": "Donbas"},
    "sahel": {"lat": 15.0, "lng": 0.0, "precision": "region", "disputed": None},
}

KNOWN_WORLD_CAPITALS = {
    "washington": (38.8951, -77.0364),
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "berlin": (52.52, 13.405),
    "tokyo": (35.6762, 139.6503),
    "new delhi": (28.6139, 77.209),
    "beijing": (39.9042, 116.4074),
    "moscow": (55.7558, 37.6173),
    "kyiv": (50.4501, 30.5234),
    "geneva": (46.2044, 6.1432),
    "cairo": (30.0444, 31.2357),
    "nairobi": (-1.2921, 36.8219),
    "buenos aires": (-34.6037, -58.3816),
    "brasilia": (-15.7975, -47.8919),
    "singapore": (1.3521, 103.8198),
    "canberra": (-35.2809, 149.13),
}

REGION_KEYS = {
    "california", "texas", "new mexico", "colorado", "arizona",
    "alberta", "catalonia", "xinjiang", "tibet", "siberia",
    "amazon", "sahel", "donbas", "crimea", "kashmir", "golan heights", "west bank",
    "gaza", "taiwan strait", "spratly islands", "western sahara", "scandinavia",
    "balkans", "caucasus", "middle east", "north africa", "sub-saharan africa",
    "latin america", "central asia", "southeast asia", "east asia", "south asia",
}

_CANONICAL_COUNTRIES = set()
for _name in WORLD_LOCATIONS:
    _canonical = canonical_country(_name)
    if _canonical:
        _CANONICAL_COUNTRIES.add(_canonical.lower())


def _ascii(value: str) -> str:
    text = value.replace("’", "'").replace("‘", "'").replace("`", "'")
    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


def _clean_location(name: str) -> str:
    text = _ascii((name or "").strip().lower())
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text)
    text = re.sub(r"^(the)\s+", "", text)
    text = re.sub(r"[.,;:]+$", "", text)
    return re.sub(r"\s+", " ", text).strip()


class Geocoder:
    def __init__(self, enable_remote: Optional[bool] = None, max_remote_calls: int = 25):
        self.enable_remote = (
            enable_remote
            if enable_remote is not None
            else os.getenv("ENABLE_REMOTE_GEOCODING", "false").lower() == "true"
        )
        self.geonames_username = os.getenv("GEONAMES_USERNAME", "").strip()
        self.max_remote_calls = max_remote_calls
        self._remote_calls = 0
        self._remote_failures = 0
        self._last_remote = 0.0
        self._cache: Dict[str, Dict[str, Any]] = {}

        for key, (lat, lng) in WORLD_LOCATIONS.items():
            cleaned = _clean_location(key)
            if not cleaned:
                continue
            precision = "country" if cleaned in _CANONICAL_COUNTRIES else ("region" if cleaned in REGION_KEYS else "city")
            self._cache[cleaned] = {"lat": lat, "lng": lng, "precision": precision, "disputed": None}
        for key, (lat, lng) in KNOWN_WORLD_CAPITALS.items():
            self._cache.setdefault(key, {"lat": lat, "lng": lng, "precision": "city", "disputed": None})

        keys = [key for key in self._cache if len(key) >= 4]
        pattern = "|".join(re.escape(key) for key in sorted(keys, key=len, reverse=True))
        self._location_pattern = re.compile(r"(?<![a-z])(" + pattern + r")(?![a-z])", re.IGNORECASE) if pattern else None
        self._request_session = requests.Session()
        self._request_session.headers.update({"User-Agent": "GlobeNewsAtlas/1.0 (geocoding)"})

    def geocode(self, location_name: str) -> Optional[Dict[str, Any]]:
        if not location_name:
            return None
        cleaned = _clean_location(location_name)

        for disputed, info in DISPUTED_LOCATIONS.items():
            if disputed in cleaned:
                return {
                    "name": location_name,
                    "lat": info["lat"],
                    "lng": info["lng"],
                    "precision": info["precision"],
                    "is_disputed": info["disputed"],
                }

        if cleaned in DEMONYM_MAP:
            cleaned = DEMONYM_MAP[cleaned]

        if cleaned in self._cache:
            info = self._cache[cleaned]
            return {
                "name": location_name,
                "lat": info["lat"],
                "lng": info["lng"],
                "precision": info["precision"],
                "is_disputed": info.get("disputed"),
            }

        canonical = canonical_country(cleaned)
        if canonical:
            key = canonical.lower()
            if key in self._cache:
                info = self._cache[key]
                return {
                    "name": canonical,
                    "lat": info["lat"],
                    "lng": info["lng"],
                    "precision": "country",
                    "is_disputed": None,
                }

        if self._location_pattern:
            match = self._location_pattern.search(cleaned)
            if match:
                key = match.group(1).lower()
                info = self._cache.get(key)
                if info:
                    return {
                        "name": location_name,
                        "lat": info["lat"],
                        "lng": info["lng"],
                        "precision": info["precision"],
                        "is_disputed": info.get("disputed"),
                    }

        return self._remote_geocode(cleaned, location_name)

    def _remote_geocode(self, cleaned: str, original: str) -> Optional[Dict[str, Any]]:
        if not self.enable_remote or self._remote_calls >= self.max_remote_calls:
            return None
        if self._remote_failures >= 2:
            self.enable_remote = False
            logger.warning("Disabling remote geocoding for this run after repeated failures.")
            return None
        self._remote_calls += 1
        elapsed = time.time() - self._last_remote
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        self._last_remote = time.time()

        try:
            if self.geonames_username:
                response = self._request_session.get(
                    "https://secure.geonames.org/searchJSON",
                    params={"q": cleaned, "maxRows": 1, "username": self.geonames_username},
                    timeout=6,
                )
                if response.status_code == 401:
                    self.enable_remote = False
                    logger.warning(
                        "GeoNames rejected the account (free web service not enabled). "
                        "Enable it at https://www.geonames.org/manageaccount; continuing with the offline gazetteer."
                    )
                    return None
                response.raise_for_status()
                rows = response.json().get("geonames") or []
                if rows:
                    row = rows[0]
                    result = {
                        "name": original,
                        "lat": float(row["lat"]),
                        "lng": float(row["lng"]),
                        "precision": "city",
                        "is_disputed": None,
                    }
                    self._cache[cleaned] = {
                        "lat": result["lat"],
                        "lng": result["lng"],
                        "precision": result["precision"],
                        "disputed": None,
                    }
                    return result
            response = self._request_session.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": cleaned, "format": "json", "limit": 1},
                timeout=6,
            )
            response.raise_for_status()
            rows = response.json()
            if rows:
                result = {
                    "name": original,
                    "lat": float(rows[0]["lat"]),
                    "lng": float(rows[0]["lon"]),
                    "precision": "city",
                    "is_disputed": None,
                }
                self._cache[cleaned] = {
                    "lat": result["lat"],
                    "lng": result["lng"],
                    "precision": result["precision"],
                    "disputed": None,
                }
                return result
        except Exception as exc:
            self._remote_failures += 1
            logger.warning("Remote geocoding failed for %r: %s", cleaned, type(exc).__name__)
        return None

    def geocode_article(
        self,
        article: Dict[str, Any],
        entities: Optional[Dict[str, List[str]]] = None,
        title_entities: Optional[Dict[str, List[str]]] = None,
    ) -> Optional[Dict[str, Any]]:
        lat, lng = article.get("lat"), article.get("lng")
        try:
            if lat is not None and lng is not None:
                lat_f, lng_f = float(lat), float(lng)
                if -90 <= lat_f <= 90 and -180 <= lng_f <= 180 and not (abs(lat_f) < 0.001 and abs(lng_f) < 0.001):
                    return {
                        "name": article.get("location_name") or "",
                        "lat": lat_f,
                        "lng": lng_f,
                        "precision": article.get("geo_precision") or "region",
                        "is_disputed": None,
                    }
        except (TypeError, ValueError):
            pass

        country_fallback: Optional[Dict[str, Any]] = None
        location_name = article.get("location_name")
        if location_name:
            info = self.geocode(str(location_name))
            if info and info["precision"] in {"city", "region"}:
                return info
            country_fallback = info

        # The headline is the strongest signal for the story's dateline. A city
        # in the article body is often the outlet's bureau or an incidental
        # mention, which is how a French riot story was once plotted in New York.
        for location in ((title_entities or {}).get("locations") or [])[:8]:
            info = self.geocode(location)
            if info and info["precision"] in {"city", "region"}:
                return info
            country_fallback = country_fallback or info

        for country in ((title_entities or {}).get("countries") or [])[:6]:
            info = self.geocode(country)
            if info:
                info = dict(info)
                info["precision"] = "country"
                info["name"] = country
                return info

        locations = (entities or {}).get("locations", []) or []
        for location in locations[:8]:
            info = self.geocode(location)
            if not info:
                continue
            if info["precision"] in {"city", "region"}:
                return info
            country_fallback = country_fallback or info

        for country in article.get("countries") or []:
            info = self.geocode(country)
            if info:
                info = dict(info)
                info["precision"] = "country"
                info["name"] = country
                return info

        return country_fallback
