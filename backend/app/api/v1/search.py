from fastapi import APIRouter, Query, Response
from typing import Optional
from app.services.search_service import search_service
from app.schemas.search import SearchResult

router = APIRouter()


@router.get("/search", response_model=list[SearchResult])
async def search(
    response: Response,
    q: str = Query("", description="Keywords matched against title, summary and location"),
    category: Optional[str] = Query(None, description="Category filter"),
    window: str = Query("30d", pattern="^(1h|24h|7d|30d)$"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search events in the gold snapshot by keyword or category.

    The body stays a capped JSON array for existing clients; the true number
    of matches (before the limit) is exposed in ``X-Total-Count``.
    """
    results, total = search_service.search_events_with_total(
        query=q,
        category=category,
        window=window,
        limit=limit,
    )
    response.headers["X-Total-Count"] = str(total)
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"
    return results
