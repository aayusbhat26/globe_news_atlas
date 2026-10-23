import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.schemas.event import (
    CoverageColumn,
    EventDetailResponse,
    HoverCardResponse,
    SpectrumBar,
    TimelineEntry,
)
from app.services.snapshot_service import snapshot_service

logger = logging.getLogger("app.events")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()


def _parse(value: Any) -> Optional[datetime]:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _relative(value: Any) -> str:
    parsed = _parse(value)
    if not parsed:
        return ""
    seconds = max((datetime.now(timezone.utc) - parsed).total_seconds(), 0)
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _spectrum(value: Any) -> SpectrumBar:
    data = value if isinstance(value, dict) else {}
    return SpectrumBar(
        left=int(data.get("left") or 0),
        centre=int(data.get("centre") or 0),
        right=int(data.get("right") or 0),
        unrated=int(data.get("unrated") or 0),
    )


class EventService:
    def _find_event(self, event_id: str) -> Optional[Tuple[Dict[str, Any], str]]:
        for window in ("30d", "24h", "7d", "1h"):
            snapshot = snapshot_service.get_snapshot(window)
            for event in snapshot.get("events", []):
                if event.get("id") == event_id:
                    return event, window
        return None

    def get_hover_card(self, event_id: str) -> Optional[HoverCardResponse]:
        found = self._find_event(event_id)
        if not found:
            return None
        event, _ = found
        detail = snapshot_service.get_detail(event_id) or {}

        warning = detail.get("content_warning") if event.get("cw") else None
        return HoverCardResponse(
            id=event["id"],
            title=_text(event.get("t")),
            summary=_text(event.get("sum")) or _text(detail.get("summary")),
            category=_text(event.get("cat")),
            status=_text(event.get("st")),
            updated_at=_parse(event.get("at") or detail.get("last_updated")),
            updated_relative=_relative(event.get("at") or detail.get("last_updated")),
            outlet_count=int(event.get("oc") or 0),
            spectrum=_spectrum(event.get("sp") or detail.get("spectrum")),
            is_single_source=bool(event.get("ss")),
            has_coverage_gap=bool(event.get("cg")),
            social_buzz=max(0.0, min(float(event.get("sb") or 0.0), 1.0)),
            content_warning=warning,
            summary_method=_text(detail.get("summary_method")) or "extractive",
            location_name=_text(event.get("loc")) or _text(detail.get("location_name")),
            geo_precision=_text(event.get("gp")) or _text(detail.get("geo_precision")),
        )

    def get_event_detail(self, event_id: str) -> Optional[EventDetailResponse]:
        detail = snapshot_service.get_detail(event_id)
        if not detail:
            found = self._find_event(event_id)
            if not found:
                return None
            return self._fallback_detail(*found)
        return self._build_detail(detail)

    def _build_detail(self, detail: Dict[str, Any]) -> EventDetailResponse:
        timeline = []
        for entry in detail.get("timeline") or []:
            stamp = _parse(entry.get("timestamp"))
            if not stamp:
                continue
            timeline.append(
                TimelineEntry(
                    timestamp=stamp,
                    description=_text(entry.get("description")),
                    source_count=int(entry.get("source_count") or 1),
                )
            )

        coverage = []
        for column in detail.get("coverage") or []:
            if not isinstance(column, dict):
                continue
            coverage.append(
                CoverageColumn(
                    camp=_text(column.get("camp")),
                    outlet_count=int(column.get("outlet_count") or 0),
                    article_count=int(column.get("article_count") or 0),
                    framing_note=_text(column.get("framing_note")),
                    sample_headlines=[
                        headline
                        for headline in column.get("sample_headlines") or []
                        if isinstance(headline, dict)
                    ],
                    sentiment=column.get("sentiment"),
                )
            )

        spectrum = _spectrum(detail.get("spectrum"))
        outlets = int(detail.get("outlet_count") or 0)
        if not outlets:
            outlets = spectrum.left + spectrum.centre + spectrum.right + spectrum.unrated

        return EventDetailResponse(
            id=_text(detail.get("id")),
            title=_text(detail.get("title")),
            status=_text(detail.get("status")),
            category=_text(detail.get("category")),
            severity=_text(detail.get("severity")) or "low",
            first_reported=_parse(detail.get("first_reported")),
            last_updated=_parse(detail.get("last_updated")),
            summary=_text(detail.get("summary")),
            summary_method=_text(detail.get("summary_method")) or "extractive",
            confidence=float(detail.get("confidence") or 0.0),
            excerpt=_text(detail.get("excerpt")),
            timeline=timeline,
            coverage=coverage,
            lat=detail.get("lat"),
            lng=detail.get("lng"),
            geo_precision=_text(detail.get("geo_precision")),
            location_name=_text(detail.get("location_name")),
            reddit_threads=int(detail.get("reddit_threads") or 0),
            bluesky_posts=int(detail.get("bluesky_posts") or 0),
            outlet_count=outlets,
            article_count=int(detail.get("article_count") or 0),
            source_count=int(detail.get("source_count") or 0),
            is_single_source=bool(detail.get("is_single_source")),
            has_coverage_gap=bool(detail.get("has_coverage_gap")),
            has_official_source=bool(detail.get("has_official_source")),
            content_warning=detail.get("content_warning"),
            revision=int(detail.get("revision") or 1),
            countries=[_text(country) for country in detail.get("countries") or [] if _text(country)],
            spectrum=spectrum,
            sources=[
                source
                for source in detail.get("sources") or []
                if isinstance(source, dict) and source.get("url")
            ],
            related_event_ids=list(detail.get("related_event_ids") or []),
            related_relation_ids=list(detail.get("related_relation_ids") or []),
            corrections=[
                correction
                for correction in detail.get("corrections") or []
                if isinstance(correction, dict)
            ],
        )

    def _fallback_detail(
        self, event: Dict[str, Any], window: str
    ) -> EventDetailResponse:
        """Build an honest payload when the detail file has no row for an event."""
        spectrum = _spectrum(event.get("sp"))
        stamps = _parse(event.get("at"))
        categories = (
            ("left", spectrum.left),
            ("centre", spectrum.centre),
            ("right", spectrum.right),
            ("unrated", spectrum.unrated),
        )
        coverage = [
            CoverageColumn(
                camp=camp,
                outlet_count=count,
                article_count=count,
                framing_note=f"{count} {camp}-rated outlet(s) reported this event.",
                sample_headlines=[],
            )
            for camp, count in categories
            if count
        ]
        return EventDetailResponse(
            id=_text(event.get("id")),
            title=_text(event.get("t")),
            status=_text(event.get("st")),
            category=_text(event.get("cat")),
            severity="low",
            first_reported=stamps,
            last_updated=stamps,
            summary=_text(event.get("sum")),
            summary_method="extractive",
            lat=event.get("lat"),
            lng=event.get("lng"),
            geo_precision=_text(event.get("gp")),
            location_name=_text(event.get("loc")),
            outlet_count=int(event.get("oc") or 0),
            is_single_source=bool(event.get("ss")),
            has_coverage_gap=bool(event.get("cg")),
            content_warning=None,
            spectrum=spectrum,
            coverage=coverage,
        )


event_service = EventService()
