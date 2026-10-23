"""Editorial lenses: thin coverage, storylines, momentum and replay."""

from typing import Any

from fastapi import APIRouter, Query, Response

from app.services.atlas_service import atlas_service

router = APIRouter()
_WINDOW = r"^(1h|24h|7d|30d)$"


@router.get("/lenses/thin")
async def thin_file(
    response: Response,
    window: str = Query("24h", pattern=_WINDOW),
    limit: int = Query(60, ge=1, le=120),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=60"
    return atlas_service.get_thin_file(window, limit)


@router.get("/storylines")
async def storylines(
    response: Response,
    window: str = Query("24h", pattern=_WINDOW),
    limit: int = Query(40, ge=1, le=80),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=60"
    return atlas_service.get_storylines(window, limit)


@router.get("/pulse")
async def pulse(
    response: Response,
    window: str = Query("24h", pattern=_WINDOW),
    limit: int = Query(12, ge=1, le=30),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=60"
    return atlas_service.get_pulse(window, limit)


@router.get("/rewind")
async def rewind(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=60"
    return atlas_service.get_rewind()
