from fastapi import APIRouter, HTTPException, Path
from typing import List
from app.services.snapshot_service import snapshot_service
from app.schemas.snapshot import SnapshotArc

router = APIRouter()


@router.get("/relations", response_model=List[SnapshotArc])
async def list_relations():
    """
    Returns active geopolitical bilateral & multilateral relations.
    """
    snapshot = snapshot_service.get_snapshot("24h")
    return snapshot.get("arcs", [])


@router.get("/relations/{relation_id}", response_model=SnapshotArc)
async def get_relation(
    relation_id: str = Path(...)
):
    snapshot = snapshot_service.get_snapshot("24h")
    for arc in snapshot.get("arcs", []):
        if arc["id"] == relation_id:
            return arc
    raise HTTPException(status_code=404, detail="Relation arc not found")
