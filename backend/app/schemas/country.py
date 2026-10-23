from typing import Dict, List, Optional

from pydantic import BaseModel


class CountryBriefEvent(BaseModel):
    """Compact row shown in the country desk."""

    id: str
    title: str
    summary: str = ""
    category: str
    importance: float = 0.0
    updated_at: Optional[str] = None
    location: str = ""
    source: str = ""
    outlet_count: int = 0
    source_count: int = 0
    severity: str = ""
    is_single_source: bool = False
    has_coverage_gap: bool = False
    content_warning: bool = False


class CountryBriefSection(BaseModel):
    key: str
    count: int = 0
    events: List[CountryBriefEvent] = []


class CountryBriefResponse(BaseModel):
    country: str
    iso2: str = ""
    window: str
    generated_at: Optional[str] = None
    available: bool = False
    total_events: int = 0
    brief_events: int = 0
    total_reports: int = 0
    total_outlets: int = 0
    counts: Dict[str, int] = {}
    sections: List[CountryBriefSection] = []
