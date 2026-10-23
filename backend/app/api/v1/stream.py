import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.snapshot_service import snapshot_service

router = APIRouter()


@router.get("/stream")
async def event_stream(request: Request):
    """Server-Sent Events stream that fires when the pipeline publishes a new snapshot."""
    version = snapshot_service.get_version()

    async def event_generator():
        nonlocal version
        yield "retry: 15000\n\n"
        while not await request.is_disconnected():
            current = snapshot_service.get_version()
            if current != version:
                version = current
                manifest = snapshot_service.get_manifest()
                payload = {
                    "type": "snapshot_updated",
                    "run_id": manifest.get("run_id"),
                    "generated_at": manifest.get("generated_at"),
                    "windows": manifest.get("windows", {}),
                }
                yield f"event: snapshot_updated\ndata: {json.dumps(payload)}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(max(settings.stream_poll_seconds, 2))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
