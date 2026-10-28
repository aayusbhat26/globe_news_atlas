"""Build the compact SQLite FTS5 index used by the search API.

Only event-level text is indexed. Crawled article text stays server-side; the
search API returns the existing short summary and source attribution, never the
full article body.
"""
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pipeline.storage.search_index")

MAX_BODY_CHARS = 8000
MAX_ARTICLE_CHARS = 2500


_ATTRIBUTION_PREFIX = re.compile(
    r"^\s*[^.!?\n]{1,120}?\s+(?:reports?|adds?|says?|said)\s*:\s*",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def indexable_summary(summary: Any) -> str:
    """Strip the synthetic "Outlet reports:" prefix before indexing.

    The prefix repeats the outlet name, so indexing it made a query for "India"
    match unrelated Times of India stories.
    """
    cleaned = _text(summary)
    if not cleaned:
        return ""
    return _ATTRIBUTION_PREFIX.sub("", cleaned, count=1).strip()


def _event_rows(
    snapshots: Dict[str, Dict[str, Any]],
    contexts: Dict[str, Dict[str, Any]],
    content_by_article: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen = set()
    rows: List[Dict[str, Any]] = []
    for snapshot in snapshots.values():
        for event in snapshot.get("events") or []:
            event_id = _text(event.get("id"))
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            context = contexts.get(event_id) or {}
            cluster = context.get("cluster") or []
            body_parts: List[str] = []
            used = 0
            for article in sorted(
                cluster,
                key=lambda item: _text(item.get("published_at")),
                reverse=True,
            ):
                content_row = content_by_article.get(_text(article.get("id"))) or {}
                piece = _text(content_row.get("text")) or " ".join(
                    part
                    for part in [_text(article.get("title")), _text(article.get("snippet"))]
                    if part
                )
                if not piece:
                    continue
                remaining = MAX_BODY_CHARS - used
                if remaining <= 0:
                    break
                body_parts.append(piece[: min(MAX_ARTICLE_CHARS, remaining)])
                used += len(body_parts[-1]) + 1
            primary = context.get("primary") or {}
            source_url = _text(primary.get("url") or primary.get("canonical_url"))
            if not source_url and cluster:
                source_url = _text(cluster[0].get("url") or cluster[0].get("canonical_url"))
            rows.append(
                {
                    "event_id": event_id,
                    "title": _text(event.get("t")),
                    "body": "\n".join(body_parts),
                    "summary": indexable_summary(event.get("sum")),
                    "countries": ", ".join(context.get("countries") or []),
                    "location": _text(event.get("loc")),
                    "outlet": _text(event.get("src")),
                    "category": _text(event.get("cat")),
                    "updated_at": _text(event.get("at")),
                    "importance": float(event.get("imp") or 0.0),
                    "lat": float(event.get("lat") or 0.0),
                    "lng": float(event.get("lng") or 0.0),
                    "status": _text(event.get("st")),
                    "outlet_count": int(event.get("oc") or 0),
                    "url": source_url,
                }
            )
    return rows


def build_search_index(
    output_path: Path,
    snapshots: Dict[str, Dict[str, Any]],
    contexts: Dict[str, Dict[str, Any]],
    content_by_article: Optional[Dict[str, Dict[str, Any]]] = None,
) -> int:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass

    rows = _event_rows(snapshots, contexts, content_by_article or {})
    connection = sqlite3.connect(str(temporary))
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            """
            CREATE VIRTUAL TABLE events_fts USING fts5(
                event_id UNINDEXED,
                title,
                body,
                summary,
                countries,
                location,
                outlet UNINDEXED,
                category UNINDEXED,
                updated_at UNINDEXED,
                importance UNINDEXED,
                lat UNINDEXED,
                lng UNINDEXED,
                status UNINDEXED,
                outlet_count UNINDEXED,
                url UNINDEXED,
                tokenize = 'unicode61 remove_diacritics 2'
            )
            """
        )
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("generated_at", datetime.now(timezone.utc).isoformat()),
                ("events", str(len(rows))),
            ],
        )
        connection.executemany(
            """
            INSERT INTO events_fts (
                event_id, title, body, summary, countries, location, outlet,
                category, updated_at, importance, lat, lng, status, outlet_count, url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["event_id"],
                    row["title"],
                    row["body"],
                    row["summary"],
                    row["countries"],
                    row["location"],
                    row["outlet"],
                    row["category"],
                    row["updated_at"],
                    row["importance"],
                    row["lat"],
                    row["lng"],
                    row["status"],
                    row["outlet_count"],
                    row["url"],
                )
                for row in rows
            ],
        )
        connection.commit()
    finally:
        connection.close()

    os.replace(temporary, output_path)
    logger.info("Search index built with %d events at %s", len(rows), output_path)
    return len(rows)
