from fastapi import APIRouter, Request

from app.middleware.rate_limit import limiter
from app.schemas.feedback import FeedbackAck, FeedbackCreate
from app.services.feedback_service import feedback_service

router = APIRouter()


@router.post("/feedback", response_model=FeedbackAck, status_code=201)
@limiter.limit("10/minute")
async def create_feedback(request: Request, payload: FeedbackCreate):
    """Persist a user-submitted correction report for the pipeline maintainers."""
    report_id = feedback_service.record(payload.model_dump())
    return FeedbackAck(status="recorded", id=report_id)
