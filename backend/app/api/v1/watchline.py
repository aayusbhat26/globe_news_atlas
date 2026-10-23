"""Reader watchlines: pinned places and followed storylines."""

from typing import Any, List

from fastapi import APIRouter, Depends, Query, Request

from app.api.v1.auth import require_csrf, require_user
from app.auth.service import SessionContext
from app.middleware.rate_limit import limiter
from app.schemas.watchline import WatchlineEntryRequest
from app.services.watchline_service import watchline_service

router = APIRouter(prefix="/watchline")


@router.get("/public")
@limiter.limit("60/minute")
def public_watchline(
    request: Request,
    keys: List[str] = Query(default=[]),
    window: str = Query("24h", pattern="^(1h|24h|7d|30d)$"),
) -> dict[str, Any]:
    """Read-only feed for a shared desk link. No reader data is involved."""
    return watchline_service.public_feed(keys, window)


@router.get("/options")
@limiter.limit("60/minute")
def watchline_options(request: Request) -> dict[str, Any]:
    return watchline_service.options()


@router.get("")
@limiter.limit("60/minute")
def get_watchline(
    request: Request,
    window: str = Query("24h", pattern="^(1h|24h|7d|30d)$"),
    session: SessionContext = Depends(require_user),
) -> dict[str, Any]:
    return watchline_service.user_feed(session.user["user_id"], window)


@router.get("/entries")
@limiter.limit("120/minute")
def list_entries(
    request: Request,
    session: SessionContext = Depends(require_user),
) -> dict[str, Any]:
    return {"entries": watchline_service.list_entries(session.user["user_id"])}


@router.post(
    "/entries",
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("30/minute")
def add_entry(
    request: Request,
    payload: WatchlineEntryRequest,
    session: SessionContext = Depends(require_user),
) -> dict[str, Any]:
    return watchline_service.add_entry(
        session.user["user_id"], payload.kind, payload.key, payload.label
    )


@router.delete("/entries/{entry_id}", dependencies=[Depends(require_csrf)])
@limiter.limit("30/minute")
def remove_entry(
    request: Request,
    entry_id: str,
    session: SessionContext = Depends(require_user),
) -> dict[str, Any]:
    return watchline_service.remove_entry(session.user["user_id"], entry_id)


@router.post("/seen", dependencies=[Depends(require_csrf)])
@limiter.limit("60/minute")
def mark_seen(
    request: Request,
    session: SessionContext = Depends(require_user),
) -> dict[str, Any]:
    return watchline_service.mark_seen(session.user["user_id"])
