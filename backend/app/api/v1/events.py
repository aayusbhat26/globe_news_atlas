from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request
from app.config import settings
from app.services.atlas_service import atlas_service
from app.services.event_service import event_service
from app.schemas.event import HoverCardResponse, EventDetailResponse

router = APIRouter()


@router.get("/events/{event_id}/card", response_model=HoverCardResponse)
async def get_event_card(
    event_id: str = Path(..., description="ID of the event to preview")
):
    """
    Ultra-low latency (<150ms) endpoint powering desktop and mobile globe hover cards.
    """
    card = event_service.get_hover_card(event_id)
    if not card:
        raise HTTPException(status_code=404, detail="Event not found in active snapshot")
    return card


@router.get("/events/{event_id}/citation")
async def get_event_citation(
    request: Request,
    event_id: str = Path(..., description="ID of the event"),
) -> dict[str, Any]:
    base = (
        settings.public_base_url
        or settings.app_base_url
        or str(request.base_url)
    )
    citation = atlas_service.get_citation(event_id, base)
    if not citation:
        raise HTTPException(status_code=404, detail="Event not found")
    return citation


@router.get("/events/{event_id}", response_model=EventDetailResponse)
async def get_event_detail(
    event_id: str = Path(..., description="ID of the event")
):
    """
    Returns complete event data, 3-column media framing analysis, timeline, and cited sources.
    """
    detail = event_service.get_event_detail(event_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Event not found")
    return detail
