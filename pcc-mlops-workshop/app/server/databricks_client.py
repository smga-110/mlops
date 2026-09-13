"""Databricks connectivity: a shared WorkspaceClient plus helpers for querying the
SQL warehouse and the model serving endpoint.

Auth follows the default SDK chain. Inside a Databricks App the platform injects
``DATABRICKS_CLIENT_ID`` / ``DATABRICKS_CLIENT_SECRET`` / ``DATABRICKS_HOST`` for the
app's service principal, so ``WorkspaceClient()`` needs no arguments. Locally we
fall back to the ``DATABRICKS_PROFILE`` CLI profile.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import os

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from .config import IS_DATABRICKS_APP, settings

_client: WorkspaceClient | None = None
_client_lock = threading.Lock()


def get_client() -> WorkspaceClient:
    """Return a process-wide singleton WorkspaceClient."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if IS_DATABRICKS_APP:
                    _client = WorkspaceClient()
                else:
                    profile = os.environ.get("DATABRICKS_PROFILE")
                    _client = (
                        WorkspaceClient(profile=profile) if profile else WorkspaceClient()
                    )
    return _client


# --------------------------------------------------------------------------- #
# SQL warehouse
# --------------------------------------------------------------------------- #
_TERMINAL = {
    StatementState.SUCCEEDED,
    StatementState.FAILED,
    StatementState.CANCELED,
    StatementState.CLOSED,
}


def run_sql(statement: str, timeout_s: float = 60.0) -> list[dict[str, Any]]:
    """Execute a SQL statement on the configured warehouse and return rows as dicts.

    Only trusted, code-defined statements are passed here (table/endpoint names come
    from environment config, never from end-user input), so string interpolation of
    identifiers upstream is safe. The only user-supplied value in the whole app is the
    patient id, which flows through the serving endpoint, not this function.
    """
    w = get_client()
    resp = w.statement_execution.execute_statement(
        warehouse_id=settings.warehouse_id,
        statement=statement,
        wait_timeout="30s",
    )

    deadline = time.monotonic() + timeout_s
    while resp.status and resp.status.state not in _TERMINAL:
        if time.monotonic() > deadline:
            raise TimeoutError("SQL statement did not complete before the timeout")
        time.sleep(1.0)
        resp = w.statement_execution.get_statement(resp.statement_id)

    state = resp.status.state if resp.status else None
    if state != StatementState.SUCCEEDED:
        err = getattr(resp.status, "error", None)
        msg = getattr(err, "message", None) or err or state
        raise RuntimeError(f"SQL statement failed ({state}): {msg}")

    if not resp.manifest or not resp.manifest.schema or not resp.manifest.schema.columns:
        return []
    columns = [c.name for c in resp.manifest.schema.columns]
    data = (resp.result.data_array if resp.result and resp.result.data_array else []) or []
    return [dict(zip(columns, row)) for row in data]


# --------------------------------------------------------------------------- #
# Model serving endpoint
# --------------------------------------------------------------------------- #
def score_patient(patient_id: int) -> dict[str, Any]:
    """Query the feature-store serving endpoint with just a patient key.

    The endpoint performs an automatic online feature lookup, so the request body is
    only ``{"dataframe_records": [{"<patient_id_key>": <id>}]}``.
    """
    w = get_client()
    started = time.perf_counter()
    resp = w.serving_endpoints.query(
        name=settings.endpoint_name,
        dataframe_records=[{settings.patient_id_key: patient_id}],
    )
    latency_ms = (time.perf_counter() - started) * 1000.0

    payload = resp.as_dict() if hasattr(resp, "as_dict") else {}
    predictions = payload.get("predictions") or getattr(resp, "predictions", None)
    if not predictions:
        raise RuntimeError("Serving endpoint returned no predictions")

    prediction = int(predictions[0])
    return {
        "patient_id": patient_id,
        "prediction": prediction,
        "risk": "HIGH" if prediction == 1 else "LOW",
        "latency_ms": round(latency_ms, 1),
        "endpoint": settings.endpoint_name,
    }
