from fastapi import APIRouter, Query, Response

from app.config import settings
from app.schemas.country import CountryBriefResponse
from app.services.country_service import country_service

router = APIRouter()


@router.get("/countries/brief", response_model=CountryBriefResponse)
async def get_country_brief(
    response: Response,
    name: str = Query(..., min_length=1, max_length=120, description="Country name from the map label"),
    iso2: str = Query("", max_length=8, description="Optional ISO 3166-1 alpha-2 code"),
    window: str = Query("24h", pattern="^(1h|24h|7d|30d)$", description="Rolling time window"),
):
    """
    Returns a ranked country briefing of protest, conflict and technology
    dispatches from the active snapshot.
    """
    data = country_service.get_brief(name=name, iso2=iso2, window=window)
    response.headers["Cache-Control"] = f"public, max-age={settings.snapshot_refresh_seconds}"
    return data
