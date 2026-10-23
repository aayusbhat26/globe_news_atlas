import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.schemas.search import SearchResult
from app.services.snapshot_service import snapshot_service

logger = logging.getLogger("app.search")

WINDOW_MINUTES = {"1h": 60, "24h": 24 * 60, "7d": 7 * 24 * 60, "30d": 30 * 24 * 60}
MAX_RESULTS = 100


def _match_expression(query: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[^\W_]+", query.lower(), re.UNICODE)
        if len(token) >= 2
    ][:12]
    return " AND ".join(f'"{token}"*' for token in tokens)


class SearchService:
    def _search_index(
        self,
        query: str,
        category: Optional[str],
        window: str,
        limit: int,
    ) -> Optional[List[SearchResult]]:
        index_path = snapshot_service.root / "search_index.sqlite3"
        if not index_path.is_file():
            return None
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES[window])
        ).isoformat()
        match = _match_expression(query)
        clauses = ["updated_at >= ?"]
        params: list = [cutoff]
        if category:
            clauses.append("category = ?")
            params.append(category)
        if match:
            clauses.insert(0, "events_fts MATCH ?")
            params.insert(0, match)
        params.append(max(1, min(limit, MAX_RESULTS)))
        order = "bm25(events_fts), CAST(importance AS REAL) DESC" if match else "CAST(importance AS REAL) DESC, updated_at DESC"
        sql = f"""
            SELECT event_id, title, category, lat, lng, importance, status,
                   outlet_count, summary, location, updated_at
            FROM events_fts
            WHERE {' AND '.join(clauses)}
            ORDER BY {order}
            LIMIT ?
        """
        try:
            connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, timeout=2)
            try:
                rows = connection.execute(sql, params).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            logger.warning("Full-text index unavailable, using snapshot fallback: %s", exc)
            return None

        return [
            SearchResult(
                id=str(row[0] or ""),
                title=str(row[1] or ""),
                category=str(row[2] or ""),
                lat=float(row[3] or 0.0),
                lng=float(row[4] or 0.0),
                importance=float(row[5] or 0.0),
                status=str(row[6] or ""),
                outlet_count=int(row[7] or 0),
                summary=str(row[8] or ""),
                location_name=str(row[9] or ""),
                updated_at=row[10],
            )
            for row in rows
        ]

    def search_events(
        self,
        query: str,
        category: Optional[str] = None,
        window: str = "30d",
        limit: int = 20,
    ) -> List[SearchResult]:
        if window not in WINDOW_MINUTES:
            window = "30d"
        indexed = self._search_index(query, category, window, limit)
        if indexed is not None:
            return indexed

        snapshot = snapshot_service.get_snapshot(window)
        tokens = [token for token in query.lower().split() if token]
        results: List[SearchResult] = []

        for event in snapshot.get("events", []):
            if category and event.get("cat") != category:
                continue
            haystack = " ".join(
                str(event.get(field) or "")
                for field in ("t", "sum", "loc", "src", "cat")
            ).lower()
            if tokens and not all(token in haystack for token in tokens):
                continue
            results.append(
                SearchResult(
                    id=event["id"],
                    title=event.get("t", ""),
                    category=event.get("cat", ""),
                    lat=event.get("lat", 0.0),
                    lng=event.get("lng", 0.0),
                    importance=float(event.get("imp") or 0.0),
                    status=event.get("st", ""),
                    outlet_count=int(event.get("oc") or 0),
                    summary=event.get("sum", ""),
                    location_name=event.get("loc", ""),
                    updated_at=event.get("at"),
                )
            )

        results.sort(key=lambda result: result.importance, reverse=True)
        return results[: max(1, min(limit, MAX_RESULTS))]


search_service = SearchService()
