from typing import Literal

from pydantic import BaseModel, Field


class WatchlineEntryRequest(BaseModel):
    kind: Literal["place", "arc"]
    key: str = Field(min_length=1, max_length=120)
    label: str = Field(default="", max_length=120)
