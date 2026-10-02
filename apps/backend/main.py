"""JouleMitra Phase 1 FastAPI app. No stack traces leak to clients."""

import json
import logging
import pathlib

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from apps.backend.config import get_settings
from apps.backend.db import db_is_up
from apps.backend.routers import (
    dashboard,
    energy,
    insights,
    interventions,
    machine_health,
    optimization,
    process,
    production,
    recommendations,
    sites,
    telemetry,
)

log = logging.getLogger("joulemitra")


class _RevalidatedStatic(StaticFiles):
    """Console files are revalidated on every load, so a browser never mixes
    a cached tokens.css with a newer console.css (seen: undefined tokens)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="JouleMitra API (Phase 1)")
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": json.loads(json.dumps(exc.errors(), default=str))})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/health/components")
    def health_components():
        up = db_is_up()
        return {
            "database": "up" if up else "down",
            "simulator": "not-tracked",
            "api": "up",
        }

    app.include_router(sites.router)
    app.include_router(telemetry.router)
    app.include_router(production.router)
    app.include_router(dashboard.router)
    app.include_router(energy.router)
    app.include_router(machine_health.router)
    app.include_router(insights.router)
    app.include_router(process.router)
    app.include_router(optimization.router)
    app.include_router(recommendations.router)
    app.include_router(interventions.router)
    if get_settings().DEMO_MODE:
        from apps.backend.routers import demo
        app.include_router(demo.router)

    @app.get("/console-vendor/plotly.min.js", include_in_schema=False)
    def console_vendor_plotly():
        """Serve plotly JS from the installed package (offline-safe, no CDN)."""
        try:
            from importlib import resources

            p = resources.files("plotly") / "package_data" / "plotly.min.js"
            return FileResponse(str(p), media_type="application/javascript",
                                headers={"Cache-Control": "public, max-age=86400"})
        except (ImportError, OSError, TypeError):
            import plotly

            base = pathlib.Path(plotly.__file__).resolve().parent
            return FileResponse(
                str(base / "package_data" / "plotly.min.js"),
                media_type="application/javascript",
                headers={"Cache-Control": "public, max-age=86400"},
            )

    console_dir = pathlib.Path(__file__).resolve().parents[2] / "apps" / "console"
    app.mount("/console", _RevalidatedStatic(directory=str(console_dir), html=True), name="console")
    return app


app = create_app()
