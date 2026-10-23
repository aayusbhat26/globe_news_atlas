from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SnapshotEvent(BaseModel):
    """Compact event row rendered as a dot on the globe."""

    id: str
    lat: float
    lng: float
    cat: str
    imp: float
    t: str
    at: Optional[str] = None
    oc: int = 0
    sp: Dict[str, int] = {}
    st: str
    sb: float = 0.0
    ss: bool = False
    cg: bool = False
    cw: bool = False
    sum: str = ""
    loc: str = ""
    gp: str = ""
    src: str = ""


class SnapshotArc(BaseModel):
    """Evidence-backed bilateral relation arc."""

    id: str
    a: str
    b: str
    a_lat: Optional[float] = None
    a_lng: Optional[float] = None
    b_lat: Optional[float] = None
    b_lng: Optional[float] = None
    countries: List[str] = []
    event_ids: List[str] = []
    n: int = 0
    ty: str
    dir: str
    stg: str
    imp: float
    t: Optional[str] = None


class SnapshotResponse(BaseModel):
    ts: str
    w: str
    n: Dict[str, Any]
    events: List[SnapshotEvent]
    arcs: List[SnapshotArc]
    available: bool = False
