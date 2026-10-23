"""Editorial lenses over the gold snapshot: the Thin File, storylines,
momentum and the replay archive. All of them read existing pipeline evidence.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.event_service import event_service
from app.services.snapshot_service import snapshot_service

WINDOWS = ("1h", "24h", "7d", "30d")
THIN_LIMIT = 60
_THIN_REASONS = {
    "single_outlet": "Single outlet",
    "coverage_gap": "One-sided coverage",
    "revised": "Summary revised",
}
_BIBTEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
}


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


def _bibtex(value: str) -> str:
    return "".join(_BIBTEX_SPECIALS.get(char, char) for char in value)


def _window(value: str) -> str:
    return value if value in WINDOWS else "24h"


class AtlasService:
    # ------------------------------------------------------------ thin file
    def get_thin_file(self, window: str, limit: int = THIN_LIMIT) -> Dict[str, Any]:
        window = _window(window)
        snapshot = snapshot_service.get_snapshot(window)
        details = snapshot_service.get_details()
        events = snapshot.get("events") or []
        limit = max(1, min(int(limit or THIN_LIMIT), 120))

        items: List[Dict[str, Any]] = []
        counts = {key: 0 for key in _THIN_REASONS}
        for event in events:
            event_id = _text(event.get("id"))
            detail = details.get(event_id) or {}
            reasons: List[str] = []
            if bool(event.get("ss")) or int(event.get("oc") or 0) <= 1:
                reasons.append("single_outlet")
            if bool(event.get("cg")):
                reasons.append("coverage_gap")
            if int(detail.get("revision") or 1) > 1 and int(event.get("oc") or 0) <= 3:
                reasons.append("revised")
            if not reasons:
                continue
            for reason in reasons:
                counts[reason] += 1
            items.append(
                {
                    "id": event_id,
                    "title": _text(event.get("t")),
                    "category": _text(event.get("cat")),
                    "importance": event.get("imp"),
                    "outlet_count": int(event.get("oc") or 0),
                    "source_count": int(detail.get("source_count") or 0),
                    "revision": int(detail.get("revision") or 1),
                    "has_official_source": bool(detail.get("has_official_source")),
                    "location_name": _text(event.get("loc")),
                    "updated_at": _text(event.get("at")) or None,
                    "source": _text(event.get("src")),
                    "reasons": reasons,
                    "reason_labels": [_THIN_REASONS[reason] for reason in reasons],
                }
            )

        items.sort(
            key=lambda item: (
                -float(item.get("importance") or 0),
                _text(item.get("updated_at")),
            )
        )
        return {
            "window": window,
            "generated_at": snapshot.get("ts"),
            "total_events": len(events),
            "thin_total": len(items),
            "shown": min(len(items), limit),
            "counts": counts,
            "items": items[:limit],
        }

    # ------------------------------------------------------------ storylines
    def get_storylines(self, window: str, limit: int = 40) -> Dict[str, Any]:
        window = _window(window)
        snapshot = snapshot_service.get_snapshot(window)
        events = {
            _text(event.get("id")): event for event in snapshot.get("events") or []
        }
        limit = max(1, min(int(limit or 40), 80))
        arcs = []
        for arc in snapshot.get("arcs") or []:
            event_ids = [
                _text(event_id)
                for event_id in arc.get("event_ids") or []
                if _text(event_id) in events
            ]
            # A single co-mention is not yet a storyline; require repeated evidence.
            if len(event_ids) < 2 or int(arc.get("n") or 0) < 3:
                continue
            preview = sorted(
                (events[event_id] for event_id in event_ids),
                key=lambda event: -float(event.get("imp") or 0),
            )[:3]
            arcs.append(
                {
                    "id": _text(arc.get("id")),
                    "countries": list(arc.get("countries") or []),
                    "a": _text(arc.get("a")),
                    "b": _text(arc.get("b")),
                    "type": _text(arc.get("ty")),
                    "direction": _text(arc.get("dir")),
                    "stage": _text(arc.get("stg")),
                    "importance": arc.get("imp"),
                    "total_events": int(arc.get("n") or 0),
                    "window_events": len(event_ids),
                    "a_lat": arc.get("a_lat"),
                    "a_lng": arc.get("a_lng"),
                    "b_lat": arc.get("b_lat"),
                    "b_lng": arc.get("b_lng"),
                    "events": [
                        {
                            "id": _text(event.get("id")),
                            "title": _text(event.get("t")),
                            "category": _text(event.get("cat")),
                            "updated_at": _text(event.get("at")) or None,
                            "outlet_count": int(event.get("oc") or 0),
                        }
                        for event in preview
                    ],
                }
            )
        arcs.sort(
            key=lambda arc: (
                -float(arc.get("importance") or 0),
                -int(arc.get("window_events") or 0),
            )
        )
        return {
            "window": window,
            "generated_at": snapshot.get("ts"),
            "total_storylines": len(arcs),
            "storylines": arcs[:limit],
            "available": bool(snapshot.get("available", True)),
        }

    # ----------------------------------------------------------------- pulse
    def get_pulse(self, window: str, limit: int = 12) -> Dict[str, Any]:
        window = _window(window)
        snapshot = snapshot_service.get_snapshot(window)
        rewind = snapshot_service.get_rewind()
        frames = rewind.get("frames") if isinstance(rewind.get("frames"), list) else []
        current_ts = _parse(snapshot.get("ts"))
        limit = max(1, min(int(limit or 12), 30))

        def frame_ts(frame: Dict[str, Any]) -> Optional[datetime]:
            return _parse(frame.get("ts"))

        usable = [
            frame
            for frame in frames
            if isinstance(frame, dict)
            and frame_ts(frame)
            and (current_ts is None or frame_ts(frame) < current_ts)
        ]
        previous: Dict[str, Dict[str, Any]] = {}
        for frame in usable:
            stamp = frame_ts(frame)
            for event in frame.get("events") or []:
                event_id = _text(event.get("id"))
                if event_id:
                    previous[event_id] = {
                        "outlet_count": int(event.get("oc") or 0),
                        "at": stamp,
                        "run_id": _text(frame.get("run_id")),
                    }

        items: List[Dict[str, Any]] = []
        for event in snapshot.get("events") or []:
            event_id = _text(event.get("id"))
            prior = previous.get(event_id)
            current_outlets = int(event.get("oc") or 0)
            if prior:
                delta = current_outlets - int(prior.get("outlet_count") or 0)
                is_new = False
            else:
                delta = 0
                is_new = True
            importance = float(event.get("imp") or 0)
            if not (
                (delta >= 1 and importance >= 0.55)
                or (is_new and importance >= 0.65)
            ):
                continue
            score = (
                min(max(delta, 0), 3) * 1.8
                + importance * 1.5
                + (0.6 if is_new else 0.0)
                + float(event.get("sb") or 0) * 0.3
            )
            items.append(
                {
                    "id": event_id,
                    "title": _text(event.get("t")),
                    "category": _text(event.get("cat")),
                    "location_name": _text(event.get("loc")),
                    "importance": event.get("imp"),
                    "outlet_count": current_outlets,
                    "previous_outlets": int(prior.get("outlet_count") or 0) if prior else None,
                    "outlet_delta": delta,
                    "is_new": is_new,
                    "previous_at": prior["at"].isoformat() if prior and prior.get("at") else None,
                    "updated_at": _text(event.get("at")) or None,
                    "score": round(score, 4),
                }
            )
        items.sort(key=lambda item: (-float(item.get("score") or 0), _text(item.get("title"))))

        return {
            "available": bool(frames) and bool(snapshot.get("available", True)),
            "window": window,
            "generated_at": snapshot.get("ts"),
            "basis": {
                "frames": len(frames),
                "from": _text(frames[0].get("ts")) if frames else None,
                "to": _text(frames[-1].get("ts")) if frames else None,
            },
            "items": items[:limit],
            "has_momentum": bool(items),
        }

    # ---------------------------------------------------------------- rewind
    def get_rewind(self) -> Dict[str, Any]:
        payload = snapshot_service.get_rewind()
        frames = payload.get("frames") if isinstance(payload.get("frames"), list) else []
        return {
            "available": bool(frames),
            "generated_at": payload.get("generated_at"),
            "source_window": payload.get("source_window") or "24h",
            "history_days": payload.get("history_days"),
            "from": _text(frames[0].get("ts")) if frames else None,
            "to": _text(frames[-1].get("ts")) if frames else None,
            "count": len(frames),
            "frames": frames,
        }

    # -------------------------------------------------------------- citation
    def get_citation(self, event_id: str, base_url: str) -> Optional[Dict[str, Any]]:
        detail = event_service.get_event_detail(event_id)
        if not detail:
            return None
        url = f"{base_url.rstrip('/')}/event/{detail.id}"
        stamp = detail.first_reported or detail.last_updated or datetime.now(timezone.utc)
        accessed = datetime.now(timezone.utc)
        month = stamp.strftime("%B")
        accessed_label = f"{accessed.strftime('%B')} {accessed.day}, {accessed.year}"
        title = detail.title.rstrip(".")
        organisations = "Globe News Atlas"
        apa = (
            f"{organisations}. ({stamp.year}, {month} {stamp.day}). "
            f"{title}. Retrieved {accessed_label}, from {url}"
        )
        key = re.sub(r"[^a-z0-9]+", "", detail.id.lower())[:18] or "event"
        bibtex = "\n".join(
            [
                f"@misc{{gna-{key},",
                f"  author       = {{Globe News Atlas}},",
                f"  title        = {{{_bibtex(title)}}},",
                f"  year         = {{{stamp.year}}},",
                f"  month        = {{{stamp.strftime('%b').lower()}}},",
                f"  howpublished = {{\\url{{{url}}}}},",
                f"  note         = {{Event dossier, accessed {accessed_label}}}",
                "}",
            ]
        )
        plain = f"{title}. Globe News Atlas, {stamp.strftime('%d %B %Y')}. {url}"
        first_source = detail.sources[0] if detail.sources else None
        outlet = ""
        if isinstance(first_source, dict):
            outlet = _text(first_source.get("outlet_name"))
        elif first_source is not None:
            outlet = _text(getattr(first_source, "outlet_name", ""))
        return {
            "event_id": detail.id,
            "title": detail.title,
            "url": url,
            "accessed_at": accessed.isoformat(),
            "outlet": outlet,
            "apa": apa,
            "bibtex": bibtex,
            "plain": plain,
        }


atlas_service = AtlasService()
