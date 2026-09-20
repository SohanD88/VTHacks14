"""Point-to-point paths for a specific saved scene revision."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from app.routes.scans import require
from app.routing.planner import NoRouteError
from app.routing.scene_adapter import (
    AdapterError,
    SceneRouteRequest,
    SceneRouteResponse,
    route_scene,
)

router = APIRouter(prefix="/api/scans", tags=["routing"])


@router.post("/{scan_id}/routes", response_model=SceneRouteResponse)
def create_route(scan_id: UUID, body: SceneRouteRequest, request: Request):
    scan = require(request, scan_id)
    if scan.revision != body.revision:
        raise HTTPException(
            409, "Scene changed. Reload the saved scan and choose the points again."
        )
    if scan.status not in {"completed", "degraded"} or scan.scene is None:
        raise HTTPException(409, "Wait for a finished reconstruction before planning a route.")
    try:
        result = route_scene(scan.scene, body, str(scan_id))
    except (AdapterError, NoRouteError) as exc:
        raise HTTPException(422, str(exc)) from exc
    latest = require(request, scan_id, include_scene=False)
    if latest.revision != body.revision:
        raise HTTPException(409, "Scene changed while planning. Choose the points again.")
    return {"scan_id": str(scan_id), "revision": scan.revision, **result}
