from fastapi import APIRouter, Query
from typing import Optional
from app.services.search_service import search_service
from app.schemas.search import SearchResult

router = APIRouter()


@router.get("/search", response_model=list[SearchResult])
async def search(
    q: str = Query("", description="Keywords matched against title, summary and location"),
    category: Optional[str] = Query(None, description="Category filter"),
    window: str = Query("30d", pattern="^(1h|24h|7d|30d)$"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search events in the gold snapshot by keyword or category.
    """
    return search_service.search_events(
        query=q,
        category=category,
        window=window,
        limit=limit,
    )
