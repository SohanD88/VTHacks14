import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.config import Settings, get_settings
from app.routes.camera import router as camera_router
from app.routes.scans import router as scans_router
from app.schemas import HealthResponse
from app.services.detection import CameraDetector
from app.services.reconstruction import MockReconstructionService
from app.services.store import ScanStore

logger = logging.getLogger("spatial.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(message)s")
    api = FastAPI(title="Spatial Intelligence API", version="0.1.0")
    api.state.settings = config
    api.state.detector = CameraDetector(config.detection_confidence, config.model_cache)
    api.state.reconstruction = MockReconstructionService()
    api.state.scan_store = ScanStore(config.max_stored_scans)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )

    def error(request: Request, status: int, code: str, message: str, fields=None):
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request.state.request_id,
                    "fields": fields or [],
                }
            },
        )

    @api.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [".".join(str(p) for p in issue["loc"]) for issue in exc.errors()]
        return error(
            request,
            422,
            "validation_error",
            "Check the scan name, source, and demo preset.",
            fields,
        )

    @api.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        code = "not_found" if exc.status_code == 404 else "request_error"
        return error(request, exc.status_code, code, str(exc.detail))

    @api.middleware("http")
    async def log_requests(request: Request, call_next):
        request.state.request_id = uuid4().hex
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Request failed id=%s", request.state.request_id)
            response = error(
                request, 500, "internal_error", "Scan processing failed. Please try again."
            )
            # This middleware wraps CORS, so unexpected errors need the same allowed-origin header.
            origin = request.headers.get("origin")
            if origin in config.cors_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
                response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "%s %s status=%s duration_ms=%.1f id=%s",
            request.method,
            request.url.path,
            response.status_code,
            (perf_counter() - started) * 1000,
            request.state.request_id,
        )
        return response

    @api.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(camera={"engine": "rf-detr-nano", "model": api.state.detector.state})

    api.include_router(scans_router)
    api.include_router(camera_router)
    return api


app = create_app()
