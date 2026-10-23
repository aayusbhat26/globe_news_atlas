from fastapi import APIRouter, Query, Response
from app.config import settings
from app.services.snapshot_service import snapshot_service
from app.schemas.snapshot import SnapshotResponse

router = APIRouter()


@router.get("/snapshot", response_model=SnapshotResponse)
async def get_snapshot(
    response: Response,
    window: str = Query("24h", pattern="^(1h|24h|7d|30d)$", description="Rolling time window"),
):
    """
    Returns the latest lightweight world event snapshot produced by the pipeline.
    """
    data = snapshot_service.get_snapshot(window=window)
    response.headers["Cache-Control"] = f"public, max-age={settings.snapshot_refresh_seconds}"
    return data
