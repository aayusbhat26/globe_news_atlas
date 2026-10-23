import json
from pathlib import Path
from typing import List

from fastapi import APIRouter

from app.config import settings
from app.schemas.search import OutletResponse

router = APIRouter()


@router.get("/outlets", response_model=List[OutletResponse])
async def list_outlets():
    """Returns the seed directory of outlets used for spectrum classification."""
    outlets_file = Path(settings.seeds_dir) / "outlets.json"
    if not outlets_file.is_file():
        return []
    with open(outlets_file, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return [
        OutletResponse(
            id=outlet["id"],
            name=outlet["name"],
            domain=outlet["domain"],
            country=outlet.get("country", ""),
            language=outlet.get("language", ""),
            alignment=outlet.get("alignment", "unrated"),
            rating_source=outlet.get("rating_source"),
            reliability_score=float(outlet.get("reliability_score", 0.8)),
            paywall=bool(outlet.get("paywall", False)),
            press_freedom_index=outlet.get("press_freedom_index"),
        )
        for outlet in data
    ]
