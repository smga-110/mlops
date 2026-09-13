"""Dashboard endpoints.

One route per SQL query, matching the app's data contract:
  GET /api/metrics      headline KPIs
  GET /api/volume       request count per time bucket
  GET /api/latency      p50 / p95 latency per time bucket
  GET /api/predictions  readmit vs no-readmit counts
  GET /api/spans        latency broken down by span (feature lookup vs inference)
  GET /api/recent       most recent requests
  GET /api/config       configured asset names + sample patient ids for the UI
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .. import metrics
from ..config import settings

router = APIRouter(tags=["metrics"])


def _guard(fn, *args, **kwargs):
    """Run a query function, turning any failure into a clean 503 for the UI."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Query failed: {exc}") from exc


@router.get("/config")
def get_config() -> dict[str, Any]:
    return {
        "endpoint_name": settings.endpoint_name,
        "warehouse_id": settings.warehouse_id,
        "catalog": settings.catalog,
        "schema": settings.schema,
        "payload_table": settings.payload_fqn,
        "otel_table": settings.otel_fqn,
        "patient_id_key": settings.patient_id_key,
        "sample_patients": metrics.get_sample_patients(),
    }


@router.get("/metrics")
def get_metrics() -> dict[str, Any]:
    return _guard(metrics.get_kpis)


@router.get("/volume")
def get_volume() -> dict[str, Any]:
    return _guard(metrics.get_volume)


@router.get("/latency")
def get_latency() -> dict[str, Any]:
    return _guard(metrics.get_latency)


@router.get("/predictions")
def get_predictions() -> list[dict[str, Any]]:
    return _guard(metrics.get_predictions)


@router.get("/spans")
def get_spans() -> list[dict[str, Any]]:
    return _guard(metrics.get_spans)


@router.get("/recent")
def get_recent(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
    return _guard(metrics.get_recent, limit)
