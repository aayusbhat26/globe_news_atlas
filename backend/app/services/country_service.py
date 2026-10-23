"""Country-level briefing built from the active snapshot and event details."""
import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

from app.schemas.country import (
    CountryBriefEvent,
    CountryBriefResponse,
    CountryBriefSection,
)
from app.services.snapshot_service import snapshot_service

TOP_N = 10
BRIEF_CATEGORIES = ("protest", "conflict", "technology")
WINDOW_ORDER = ("1h", "24h", "7d", "30d")

# Natural Earth writes compact or older names for a handful of countries.
# Event details use the pipeline's canonical names, so map the short forms
# before matching.
_LABEL_ALIASES = {
    "antigua and barb": "Antigua and Barbuda",
    "bosnia and herz": "Bosnia and Herzegovina",
    "central african rep": "Central African Republic",
    "congo": "Republic of the Congo",
    "dem rep congo": "Democratic Republic of the Congo",
    "dominican rep": "Dominican Republic",
    "eq guinea": "Equatorial Guinea",
    "marshall is": "Marshall Islands",
    "s sudan": "South Sudan",
    "solomon is": "Solomon Islands",
    "somaliland": "Somalia",
    "st kitts and nevis": "Saint Kitts and Nevis",
    "st vin and gren": "Saint Vincent and the Grenadines",
    "trinidad and tobago": "Trinidad and Tobago",
}


def _normalise(value: Any) -> str:
    text = str(value or "").replace("&", " and ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


_LABEL_ALIASES_NORMALISED = {
    _normalise(alias): canonical for alias, canonical in _LABEL_ALIASES.items()
}


def _clean_iso2(value: Optional[str]) -> str:
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"[A-Z]{2}", text) else ""


def _summary(event: Dict[str, Any], detail: Dict[str, Any]) -> str:
    value = detail.get("summary") or detail.get("excerpt") or event.get("sum") or ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) <= 420:
        return text
    clipped = text[:417].rsplit(" ", 1)[0]
    return f"{clipped}…"


def _brief_row(event: Dict[str, Any], detail: Dict[str, Any]) -> CountryBriefEvent:
    sources = detail.get("sources") if isinstance(detail.get("sources"), list) else []
    primary = sources[0] if sources and isinstance(sources[0], dict) else {}
    return CountryBriefEvent(
        id=str(event.get("id") or ""),
        title=str(event.get("t") or ""),
        summary=_summary(event, detail),
        category=str(event.get("cat") or "other"),
        importance=float(event.get("imp") or 0.0),
        updated_at=event.get("at"),
        location=str(event.get("loc") or detail.get("location_name") or ""),
        source=str(event.get("src") or primary.get("outlet_name") or ""),
        outlet_count=int(event.get("oc") or 0),
        source_count=int(detail.get("source_count") or 0),
        severity=str(detail.get("severity") or ""),
        is_single_source=bool(event.get("ss")),
        has_coverage_gap=bool(event.get("cg")),
        content_warning=bool(event.get("cw")),
    )


class CountryService:
    def _resolve_target(self, name: str, iso2: str) -> Tuple[str, str, Optional[str]]:
        """Return display name, normalised key and the ISO2 if it is usable."""
        cleaned = re.sub(r"\s+", " ", name).strip()
        key = _normalise(cleaned)
        display = _LABEL_ALIASES_NORMALISED.get(key, cleaned)
        canonical_key = _normalise(display)

        canonical_by_key: Dict[str, str] = {}
        for detail in snapshot_service.get_details().values():
            for country in detail.get("countries") or []:
                canonical_by_key.setdefault(_normalise(country), str(country))
        matched = canonical_by_key.get(canonical_key)
        if matched:
            display = matched
        return display, canonical_key, _clean_iso2(iso2)

    def get_brief(self, name: str, iso2: str = "", window: str = "24h") -> CountryBriefResponse:
        snapshot = snapshot_service.get_snapshot(window)
        display, target_key, clean_iso2 = self._resolve_target(name, iso2)

        # Each snapshot is independently capped for the globe. Union the
        # selected window with every shorter window so widening the range can
        # never reduce the country's dispatch count.
        selected_index = WINDOW_ORDER.index(window) if window in WINDOW_ORDER else 1
        window_events: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        any_available = False
        for candidate in WINDOW_ORDER[: selected_index + 1]:
            candidate_snapshot = snapshot_service.get_snapshot(candidate)
            any_available = any_available or bool(candidate_snapshot.get("available"))
            for event in candidate_snapshot.get("events") or []:
                if not isinstance(event, dict):
                    continue
                event_id = str(event.get("id") or "")
                if not event_id or event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                window_events.append(event)

        matched: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        for event in window_events:
            detail = snapshot_service.get_detail(str(event.get("id") or "")) or {}
            tagged = {_normalise(country) for country in detail.get("countries") or []}
            if target_key and target_key in tagged:
                matched.append((event, detail))
                continue
            if target_key and _normalise(event.get("loc")) == target_key:
                matched.append((event, detail))

        counts = {
            category: sum(1 for event, _ in matched if event.get("cat") == category)
            for category in BRIEF_CATEGORIES
        }
        brief_items = [
            (event, detail)
            for event, detail in matched
            if event.get("cat") in BRIEF_CATEGORIES
        ]

        outlets: Set[str] = set()
        for _, detail in matched:
            for source in detail.get("sources") or []:
                if isinstance(source, dict) and source.get("outlet_name"):
                    outlets.add(str(source["outlet_name"]))
        if not outlets:
            total_outlets = max((int(event.get("oc") or 0) for event, _ in matched), default=0)
        else:
            total_outlets = len(outlets)

        sections: List[CountryBriefSection] = []

        def section(key: str, members: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> None:
            ranked = sorted(
                members,
                key=lambda pair: (
                    float(pair[0].get("imp") or 0.0),
                    str(pair[0].get("at") or ""),
                    int(pair[0].get("oc") or 0),
                ),
                reverse=True,
            )
            sections.append(
                CountryBriefSection(
                    key=key,
                    count=len(members),
                    events=[_brief_row(event, detail) for event, detail in ranked[:TOP_N]],
                )
            )

        section("all", matched)
        section("brief", brief_items)
        for category in BRIEF_CATEGORIES:
            section(
                category,
                [(event, detail) for event, detail in matched if event.get("cat") == category],
            )

        return CountryBriefResponse(
            country=display,
            iso2=clean_iso2,
            window=window,
            generated_at=snapshot.get("ts"),
            available=any_available,
            total_events=len(matched),
            brief_events=len(brief_items),
            total_reports=sum(
                int(detail.get("source_count") or event.get("oc") or 0)
                for event, detail in matched
            ),
            total_outlets=total_outlets,
            counts=counts,
            sections=sections,
        )


country_service = CountryService()
