"""Canonical raw records shared by every fetcher.

Bronze tables keep one row per retrieved item. Source-specific details live in
``source_metadata``/``raw_payload`` so silver can normalise without losing
provenance.
"""
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "cmpid",
    "ocid",
    "ito",
    "smid",
    "partner",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(raw: Any, limit: int = 2000) -> str:
    if raw is None:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", str(raw)))
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    if not parts.scheme or not parts.netloc:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k.lower() not in TRACKING_PARAMS]
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def parse_datetime(value: Any) -> Optional[str]:
    """Return an ISO-8601 UTC timestamp or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e12:
            seconds /= 1000.0
        try:
            moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            # GDELT DATEADDED is YYYYMMDDHHMMSS, not an epoch value.
            if len(text) >= 12:
                try:
                    moment = datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                    return moment.astimezone(timezone.utc).isoformat()
                except ValueError:
                    pass
            return parse_datetime(int(text))
        candidate = text.replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            try:
                moment = parsedate_to_datetime(text)
            except (TypeError, ValueError, IndexError):
                moment = None
            if moment is None:
                for pattern in ("%Y%m%d%H%M%S", "%Y%m%dT%H%M%SZ", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                    try:
                        moment = datetime.strptime(text, pattern)
                        break
                    except ValueError:
                        continue
        if moment is None:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def stable_id(*parts: Any) -> str:
    payload = "|".join(str(p or "") for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def normalise_alignment(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"left", "left_center", "leftcentre", "lean_left"}:
        return "left"
    if text in {"right", "right_center", "rightcentre", "lean_right"}:
        return "right"
    if text in {"centre", "center", "centrist", "middle"}:
        return "centre"
    return "unrated"


def _json_safe(payload: Any, depth: int = 0, max_str: int = 400) -> Any:
    if depth > 3:
        return None
    if isinstance(payload, dict):
        return {str(k): _json_safe(v, depth + 1, max_str) for k, v in list(payload.items())[:40]}
    if isinstance(payload, (list, tuple)):
        return [_json_safe(v, depth + 1, max_str) for v in list(payload)[:40]]
    if isinstance(payload, str):
        return payload[:max_str]
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    return str(payload)[:max_str]


def compact_payload(payload: Any) -> Dict[str, Any]:
    safe = _json_safe(payload)
    return safe if isinstance(safe, dict) else {"value": safe}


def make_raw_article(
    *,
    source: str,
    title: str,
    url: str,
    source_id: str = "",
    outlet: str = "",
    outlet_id: str = "",
    domain: str = "",
    alignment: str = "unrated",
    country: Optional[str] = None,
    language: str = "en",
    author: str = "",
    published_at: Any = None,
    snippet: str = "",
    content: str = "",
    is_paywalled: bool = False,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    location_name: Optional[str] = None,
    geo_precision: Optional[str] = None,
    category: Optional[str] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
    raw_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    clean_title = clean_text(title, 400)
    canonical = canonicalize_url(url)
    fetched_at = now_iso()
    return {
        "id": stable_id("article", source, source_id or canonical or clean_title, clean_title),
        "source": source,
        "source_id": str(source_id or ""),
        "title": clean_title,
        "url": url or "",
        "canonical_url": canonical,
        "outlet": clean_text(outlet, 120),
        "outlet_id": outlet_id or "",
        "domain": domain or (urlsplit(canonical).netloc if canonical else ""),
        "alignment": normalise_alignment(alignment),
        "country": country,
        "language": language or "en",
        "author": clean_text(author, 160),
        "published_at": parse_datetime(published_at) or fetched_at,
        "fetched_at": fetched_at,
        "snippet": clean_text(snippet, 1200),
        "content": clean_text(content, 6000),
        "is_paywalled": bool(is_paywalled),
        "lat": lat,
        "lng": lng,
        "location_name": clean_text(location_name, 200) or None,
        "geo_precision": geo_precision,
        "category": category,
        "source_metadata": source_metadata or {},
        "raw_payload": compact_payload(raw_payload or {}),
    }


def make_raw_social(
    *,
    source: str,
    source_id: str,
    text: str,
    url: str,
    author: str = "",
    community: str = "",
    score: int = 0,
    comments: int = 0,
    created_at: Any = None,
    matched_title: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    created = parse_datetime(created_at) or now_iso()
    return {
        "id": stable_id("social", source, source_id),
        "source": source,
        "source_id": source_id,
        "kind": "post",
        "text": clean_text(text, 1200),
        "url": url,
        "author": clean_text(author, 160),
        "community": community,
        "score": int(score or 0),
        "comments": int(comments or 0),
        "created_at": created,
        "fetched_at": now_iso(),
        "matched_title": clean_text(matched_title, 300),
        "metadata": metadata or {},
    }


def dedupe_records(records: list, key_fields=("canonical_url", "title")) -> list:
    seen = set()
    unique = []
    for record in records:
        key = "|".join(str(record.get(f) or "").lower() for f in key_fields)
        if not key.strip("|") or key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def serialise(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
