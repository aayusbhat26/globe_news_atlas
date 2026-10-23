from typing import Optional

from pydantic import BaseModel


class OutletResponse(BaseModel):
    id: str
    name: str
    domain: str
    country: str
    language: str
    alignment: str
    rating_source: Optional[str] = None
    reliability_score: float
    paywall: bool
    press_freedom_index: Optional[float] = None


class SearchQuery(BaseModel):
    q: str
    category: Optional[str] = None
    window: Optional[str] = "30d"
    limit: Optional[int] = 20


class SearchResult(BaseModel):
    id: str
    title: str
    category: str
    lat: float
    lng: float
    importance: float
    status: str
    outlet_count: int
    summary: str = ""
    location_name: str = ""
    updated_at: Optional[str] = None
