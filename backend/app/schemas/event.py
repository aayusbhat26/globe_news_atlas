from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SpectrumBar(BaseModel):
    """Counts of distinct outlets per political camp."""

    left: int = 0
    centre: int = 0
    right: int = 0
    unrated: int = 0


class HoverCardResponse(BaseModel):
    """Shown on globe dot hover — high-speed response."""

    id: str
    title: str
    summary: str = Field("", description="Summary produced by the pipeline")
    category: str
    status: str
    updated_at: Optional[datetime] = None
    updated_relative: str = ""
    outlet_count: int = 0
    spectrum: SpectrumBar
    is_single_source: bool = False
    has_coverage_gap: bool = False
    social_buzz: float = Field(0.0, ge=0.0, le=1.0)
    content_warning: Optional[str] = None
    summary_method: str = "extractive"
    location_name: str = ""
    geo_precision: str = ""


class CoverageColumn(BaseModel):
    """One column in the perspective comparison."""

    camp: str
    outlet_count: int
    article_count: int
    framing_note: str
    sample_headlines: List[Dict[str, Any]] = []
    sentiment: Optional[float] = 0.0


class TimelineEntry(BaseModel):
    timestamp: datetime
    description: str
    source_count: int


class EventSourceItem(BaseModel):
    """Cited source. Unknown pipeline fields are preserved for clients."""

    model_config = ConfigDict(extra="allow")

    url: str
    via_google_news: Optional[bool] = None


class EventDetailResponse(BaseModel):
    """Full detail payload for the event modal."""

    id: str
    title: str
    status: str
    category: str
    severity: str
    first_reported: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    summary: str = ""
    summary_method: str = "extractive"
    confidence: float = 0.0
    excerpt: str = ""

    timeline: List[TimelineEntry] = []
    coverage: List[CoverageColumn] = []

    lat: Optional[float] = None
    lng: Optional[float] = None
    geo_precision: str = ""
    location_name: str = ""

    reddit_threads: int = 0
    bluesky_posts: int = 0

    outlet_count: int = 0
    article_count: int = 0
    source_count: int = 0
    # Honest coverage accounting when the pipeline caps the citations it emits.
    sources_total: Optional[int] = None
    sources_shown: Optional[int] = None
    is_single_source: bool = False
    has_coverage_gap: bool = False
    has_official_source: bool = False
    content_warning: Optional[str] = None
    revision: int = 1

    countries: List[str] = []
    spectrum: SpectrumBar = SpectrumBar()
    sources: List[EventSourceItem] = []
    related_event_ids: List[str] = []
    related_relation_ids: List[str] = []
    corrections: List[Dict[str, Any]] = []
