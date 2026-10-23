from typing import Literal, Optional

from pydantic import BaseModel, Field

FeedbackCategory = Literal[
    "wrong_location",
    "wrong_summary",
    "wrong_spectrum",
    "missing_source",
    "disputed_territory",
    "other",
]


class FeedbackCreate(BaseModel):
    event_id: Optional[str] = Field(default=None, max_length=200)
    category: FeedbackCategory
    details: str = Field(default="", max_length=4000)


class FeedbackAck(BaseModel):
    status: str
    id: str
