"""JouleMitra Phase 1 FastAPI app. No stack traces leak to clients."""

import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from apps.backend.db import db_is_up
from apps.backend.routers import dashboard, energy, insights, interventions, machine_health, optimization, process, production, recommendations, sites, telemetry

log = logging.getLogger("joulemitra")


def create_app() -> FastAPI:
    app = FastAPI(title="JouleMitra API (Phase 1)")

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
    return app


app = create_app()
