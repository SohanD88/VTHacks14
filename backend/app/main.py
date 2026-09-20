import logging
from contextlib import asynccontextmanager
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
from app.services.blender import BlenderService
from app.services.detection import CameraDetector
from app.services.reconstruction import ReconstructionService
from app.services.store import ScanStore
from app.services.vision import VisionModels

logger = logging.getLogger("spatial.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(message)s")

    @asynccontextmanager
    async def lifespan(api):
        yield
        api.state.scan_store.close()

    api = FastAPI(title="Spatial Intelligence API", version="0.2.0", lifespan=lifespan)
    api.state.settings = config
    api.state.detector = CameraDetector(config.detection_confidence, config.model_cache)
    api.state.blender = BlenderService(config)
    api.state.reconstruction = ReconstructionService(VisionModels(config.model_cache))
    api.state.scan_store = ScanStore(
        config.data_dir, config.max_stored_scans, config.max_storage_bytes
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
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
            "Check the request fields, scene format and video upload.",
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
        if config.blender_provider == "gemini":
            from app.services.gemini import configured

            video_configured = configured(config)
        else:
            video_configured = bool(config.blender_api_key and config.blender_planner_model)
        return HealthResponse(
            camera={"engine": "rf-detr-nano", "model": api.state.detector.state},
            blender={
                "available": api.state.blender.available(),
                "video_configured": video_configured,
                "provider": config.blender_provider,
                "model": config.blender_planner_model,
                "transport": config.blender_transport,
            },
        )

    api.include_router(scans_router)
    api.include_router(camera_router)
    return api


app = create_app()
