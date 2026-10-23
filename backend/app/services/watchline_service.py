"""Account-backed watchlines: pinned countries and followed storylines.

A watchline is a small set of places and bilateral relation arcs. The feed is
computed from the active gold snapshot and event details so it always reflects
the same evidence the atlas shows, never a separate cache.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.auth.errors import AuthError
from app.auth.security import iso_ts, now_ts
from app.auth.store import auth_store
from app.services.snapshot_service import snapshot_service

MAX_ENTRIES = 8
FEED_LIMIT = 80
WINDOWS = ("1h", "24h", "7d", "30d")
RELATION_LABELS = {
    "trade": "Trade",
    "talks": "Talks",
    "sanctions": "Sanctions",
    "military": "Military",
    "aid": "Aid",
}
_ARC_ID = re.compile(r"^[a-f0-9]{8,40}$")


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


def _entry(row: Any) -> Dict[str, Any]:
    created = int(row["created_at"] or 0)
    return {
        "id": _text(row["id"]),
        "kind": _text(row["kind"]),
        "key": _text(row["key"]),
        "label": _text(row["label"]),
        "created_at": iso_ts(created),
    }


def _arc_label(arc: Dict[str, Any]) -> str:
    countries = [_text(country) for country in arc.get("countries") or [] if _text(country)]
    label = " / ".join(countries[:3])
    if not label:
        label = f"{_text(arc.get('a')) or '?'} – {_text(arc.get('b')) or '?'}"
    relation = RELATION_LABELS.get(_text(arc.get("ty")).lower())
    return f"{label} · {relation}" if relation else label


class WatchlineService:
    def list_entries(self, user_id: str) -> List[Dict[str, Any]]:
        return [_entry(row) for row in auth_store.list_watchlines(user_id)]

    def _find_arc(self, arc_id: str) -> Optional[Dict[str, Any]]:
        for window in ("24h", "7d", "30d", "1h"):
            snapshot = snapshot_service.get_snapshot(window)
            for arc in snapshot.get("arcs") or []:
                if _text(arc.get("id")) == arc_id:
                    return arc
        return None

    def add_entry(
        self, user_id: str, kind: str, key: str, label: str = ""
    ) -> Dict[str, Any]:
        kind = (kind or "").strip().lower()
        if kind not in {"place", "arc"}:
            raise AuthError(400, "invalid_watchline", "Only places and storylines can be pinned.")
        if kind == "arc":
            arc_id = (key or "").strip().lower()
            if not _ARC_ID.match(arc_id):
                raise AuthError(400, "invalid_watchline", "That storyline reference is not valid.")
            arc = self._find_arc(arc_id)
            if not arc:
                raise AuthError(404, "storyline_not_found", "That storyline is not in the current atlas.")
            key = arc_id
            label = _arc_label(arc)
        else:
            key = " ".join((key or "").split())[:80]
            if len(key) < 2:
                raise AuthError(400, "invalid_watchline", "Enter a country or place name.")
            label = " ".join((label or key).split())[:80] or key

        status, row = auth_store.add_watchline(
            user_id, kind, key.lower() if kind == "place" else key, label, MAX_ENTRIES
        )
        if status == "limit":
            raise AuthError(
                409,
                "watchline_full",
                f"A watchline holds up to {MAX_ENTRIES} desks. Remove one to add another.",
            )
        if not row:
            raise AuthError(500, "watchline_failed", "Could not save that desk.")
        if auth_store.get_watchline_seen(user_id) is None:
            auth_store.set_watchline_seen(user_id, now_ts())
        return {"status": status, "entry": _entry(row), "entries": self.list_entries(user_id)}

    def remove_entry(self, user_id: str, entry_id: str) -> Dict[str, Any]:
        if not auth_store.remove_watchline(user_id, entry_id):
            raise AuthError(404, "watchline_missing", "That desk is not on your watchline.")
        return {"status": "removed", "entries": self.list_entries(user_id)}

    def mark_seen(self, user_id: str) -> Dict[str, Any]:
        timestamp = now_ts()
        auth_store.set_watchline_seen(user_id, timestamp)
        return {"last_seen": iso_ts(timestamp)}

    # ------------------------------------------------------------------ feed
    def _country_names(self) -> Dict[str, str]:
        names: Dict[str, str] = {}
        for detail in snapshot_service.get_details().values():
            for country in detail.get("countries") or []:
                name = _text(country)
                if name:
                    names.setdefault(name.lower(), name)
        return names

    def _resolve_public_entries(self, keys: Iterable[str]) -> List[Dict[str, Any]]:
        raw = [item.strip() for item in keys if item and item.strip()]
        if len(raw) > MAX_ENTRIES:
            raise AuthError(
                400, "watchline_too_large", f"A shared watchline holds at most {MAX_ENTRIES} desks."
            )
        countries = self._country_names()
        entries: List[Dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw:
            kind, _, value = item.partition(":")
            kind = kind.strip().lower()
            value = value.strip()
            if kind not in {"place", "arc"} or not value:
                continue
            if kind == "arc":
                arc = self._find_arc(value.lower())
                if not arc:
                    continue
                key = _text(arc.get("id"))
                label = _arc_label(arc)
            else:
                key = " ".join(value.split())[:80].lower()
                label = countries.get(key, key.title()) or value
            if not key or (kind, key) in seen:
                continue
            seen.add((kind, key))
            entries.append(
                {
                    "id": f"public-{kind}-{key}",
                    "kind": kind,
                    "key": key,
                    "label": label,
                    "created_at": None,
                }
            )
        return entries

    def build_feed(
        self,
        entries: List[Dict[str, Any]],
        window: str,
        seen_at: Optional[int] = None,
        public: bool = False,
    ) -> Dict[str, Any]:
        window = window if window in WINDOWS else "24h"
        snapshot = snapshot_service.get_snapshot(window)
        details = snapshot_service.get_details()
        events = snapshot.get("events") or []
        arcs = snapshot.get("arcs") or []

        place_entries = [entry for entry in entries if entry["kind"] == "place"]
        arc_entries = {entry["key"]: entry for entry in entries if entry["kind"] == "arc"}
        matched_by: Dict[str, List[Dict[str, Any]]] = {}
        arc_window_events: Dict[str, List[str]] = {key: [] for key in arc_entries}
        snapshot_ids = {_text(event.get("id")) for event in events}

        for event in events:
            event_id = _text(event.get("id"))
            detail = details.get(event_id) or {}
            countries = [_text(country).lower() for country in detail.get("countries") or []]
            location = _text(event.get("loc")).lower()
            for entry in place_entries:
                key = entry["key"].lower()
                if key in countries or (not countries and location and key in location):
                    matched_by.setdefault(event_id, []).append(entry)

        for arc in arcs:
            arc_id = _text(arc.get("id")).lower()
            entry = arc_entries.get(arc_id)
            if not entry:
                continue
            for event_id in arc.get("event_ids") or []:
                event_id = _text(event_id)
                if event_id in snapshot_ids:
                    arc_window_events[arc_id].append(event_id)
                    matched_by.setdefault(event_id, []).append(entry)

        feed: List[Dict[str, Any]] = []
        new_count = 0
        for event in events:
            event_id = _text(event.get("id"))
            reasons = matched_by.get(event_id)
            if not reasons:
                continue
            updated = _parse(event.get("at"))
            fresh = bool(
                seen_at
                and updated
                and updated.timestamp() > seen_at
            )
            if fresh:
                new_count += 1
            item = dict(event)
            item["matched"] = [
                {"kind": entry["kind"], "key": entry["key"], "label": entry["label"]}
                for entry in reasons
            ]
            item["fresh"] = fresh
            feed.append(item)

        feed.sort(
            key=lambda item: (
                0 if item.get("fresh") else 1,
                -float(item.get("imp") or 0),
                _text(item.get("at")),
            )
        )

        followed_arcs: List[Dict[str, Any]] = []
        event_index = {_text(event.get("id")): event for event in events}
        for arc in arcs:
            arc_id = _text(arc.get("id")).lower()
            entry = arc_entries.get(arc_id)
            if not entry:
                continue
            window_ids = arc_window_events.get(arc_id, [])
            stamps = [
                _text(event_index[event_id].get("at"))
                for event_id in window_ids
                if event_id in event_index and _text(event_index[event_id].get("at"))
            ]
            followed_arcs.append(
                {
                    "id": entry["id"],
                    "arc_id": arc_id,
                    "label": entry["label"],
                    "countries": list(arc.get("countries") or []),
                    "type": _text(arc.get("ty")),
                    "direction": _text(arc.get("dir")),
                    "stage": _text(arc.get("stg")),
                    "importance": arc.get("imp"),
                    "total_events": int(arc.get("n") or 0),
                    "window_events": len(window_ids),
                    "latest_at": max(stamps) if stamps else None,
                    "event_ids": window_ids[:6],
                }
            )

        matched_total = len(feed)
        return {
            "available": bool(snapshot.get("available", True)),
            "public": public,
            "window": window,
            "generated_at": snapshot.get("ts"),
            "entries": entries,
            "feed": feed[:FEED_LIMIT],
            "feed_total": matched_total,
            "matched_total": matched_total,
            "shown": min(matched_total, FEED_LIMIT),
            "new_count": new_count if seen_at else 0,
            "last_seen": iso_ts(seen_at) if seen_at else None,
            "arcs": followed_arcs,
            "capacity": MAX_ENTRIES,
        }

    def user_feed(self, user_id: str, window: str) -> Dict[str, Any]:
        entries = self.list_entries(user_id)
        seen_at = auth_store.get_watchline_seen(user_id)
        result = self.build_feed(entries, window, seen_at=seen_at)
        result["signed_in"] = True
        return result

    def public_feed(self, keys: Iterable[str], window: str) -> Dict[str, Any]:
        entries = self._resolve_public_entries(keys)
        result = self.build_feed(entries, window, public=True)
        result["signed_in"] = False
        return result

    def options(self) -> Dict[str, Any]:
        """Countries present in today's dispatches, for the desk picker."""
        snapshot = snapshot_service.get_snapshot("24h")
        details = snapshot_service.get_details()
        counts: Dict[str, int] = {}
        for event in snapshot.get("events") or []:
            for country in details.get(_text(event.get("id")), {}).get("countries") or []:
                name = _text(country)
                if name:
                    counts[name] = counts.get(name, 0) + 1
        places = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return {
            "places": [{"name": name, "events": total} for name, total in places[:60]],
            "generated_at": snapshot.get("ts"),
        }


watchline_service = WatchlineService()
