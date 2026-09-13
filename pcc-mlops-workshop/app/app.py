"""PRTH Endpoint Monitor - FastAPI entry point.

Serves a JSON API for scoring patients and reading endpoint-performance metrics,
plus the built React single-page app as static files.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.routes import metrics as metrics_routes
from server.routes import score as score_routes

app = FastAPI(title="PRTH Endpoint Monitor", version="1.0.0")

app.include_router(score_routes.router, prefix="/api")
app.include_router(metrics_routes.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Static frontend (built React app). API routes are registered above, so the
# SPA catch-all never shadows them.
# --------------------------------------------------------------------------- #
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")
_INDEX_HTML = os.path.join(_FRONTEND_DIST, "index.html")

if os.path.isfile(_INDEX_HTML):
    _ASSETS_DIR = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_ASSETS_DIR):
        # Hashed JS/CSS bundles are served straight from here.
        app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        # Never let the SPA fallback answer API calls; everything else is the
        # single-page app, so always return index.html (assets are mounted above).
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        return FileResponse(_INDEX_HTML)

else:  # pragma: no cover - only hit before the frontend is built

    @app.get("/")
    def _no_frontend() -> dict:
        return {
            "detail": "Frontend not built. Run `npm --prefix frontend install && "
            "npm --prefix frontend run build`.",
        }
