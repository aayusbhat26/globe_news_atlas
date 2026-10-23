from fastapi import APIRouter
from app.api.v1.snapshot import router as snapshot_router
from app.api.v1.events import router as events_router
from app.api.v1.relations import router as relations_router
from app.api.v1.search import router as search_router
from app.api.v1.stream import router as stream_router
from app.api.v1.outlets import router as outlets_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.countries import router as countries_router
from app.api.v1.auth import router as auth_router
from app.api.v1.watchline import router as watchline_router
from app.api.v1.atlas import router as atlas_router

api_router = APIRouter()

api_router.include_router(snapshot_router, tags=["snapshot"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(countries_router, tags=["countries"])
api_router.include_router(relations_router, tags=["relations"])
api_router.include_router(search_router, tags=["search"])
api_router.include_router(stream_router, tags=["stream"])
api_router.include_router(outlets_router, tags=["outlets"])
api_router.include_router(feedback_router, tags=["feedback"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(watchline_router, tags=["watchline"])
api_router.include_router(atlas_router, tags=["atlas"])
