from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.schemas import ErrorResponse, ScanRequest, ScanResponse
from app.services.reconstruction import ReconstructionService
from app.services.store import ScanStore

router = APIRouter(prefix="/api/scans", tags=["scans"])


def get_reconstruction(request: Request) -> ReconstructionService:
    return request.app.state.reconstruction


def get_store(request: Request) -> ScanStore:
    return request.app.state.scan_store


@router.post(
    "",
    response_model=ScanResponse,
    status_code=201,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def create_scan(
    body: ScanRequest,
    service: ReconstructionService = Depends(get_reconstruction),
    store: ScanStore = Depends(get_store),
) -> ScanResponse:
    scan = service.reconstruct(body)
    store.save(scan)
    return scan


@router.get(
    "/{scan_id}",
    response_model=ScanResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_scan(scan_id: UUID, store: ScanStore = Depends(get_store)) -> ScanResponse:
    scan = store.get(scan_id)
    if scan is None:
        raise HTTPException(
            status_code=404, detail="Scan not found. It may have expired or the API restarted."
        )
    return scan
