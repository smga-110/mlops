"""Dashboard metric queries against the two inference / logging tables.

Every function here runs a single SQL statement against the configured warehouse
and returns plain JSON-serialisable rows. All numbers reflect the real payload +
OpenTelemetry span data produced by the served endpoint.

Only trusted, code-defined identifiers (table / column names from ``config``) are
interpolated into SQL. The one end-user value in the whole app is the patient id,
and that flows through the serving endpoint (``databricks_client.score_patient``),
never through these queries.
"""

from __future__ import annotations

import time as _time
from typing import Any

from .config import settings
from .databricks_client import run_sql

# Friendly labels for the two OpenTelemetry span names.
SPAN_LABELS = {
    "databricks_feature_store": "Feature lookup",
    "custom_model": "Model inference",
}

# 0 = no readmission predicted (low risk); 1 = 30-day readmission predicted.
RISK_LABELS = {0: "Low risk", 1: "High risk"}

# date_trunc units the volume / latency series may bucket by.
_VALID_BUCKETS = {"SECOND", "MINUTE", "HOUR", "DAY", "WEEK", "MONTH"}

# Resolved "AUTO" bucket is cached briefly so /volume and /latency don't each
# re-measure the data's time span on every dashboard load.
_auto_cache: dict[str, Any] = {"unit": None, "ts": 0.0}
_AUTO_TTL_S = 120.0


def _num(value: Any) -> float | int | None:
    """Coerce a stringified SQL numeric (the statement API returns strings) into a
    Python int/float, leaving non-numeric values untouched."""
    if value is None:
        return None
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return value


# Aim for a readable number of points on the time-series charts. We pick the
# finest unit whose *active* (non-empty) bucket count stays under this ceiling,
# so a short high-rate burst renders per-second while weeks of steady traffic
# roll up to hours/days. Keying off active-bucket density (not the raw min/max
# span) keeps a few straggler requests from coarsening an otherwise tight burst.
_TARGET_POINTS = 300


def _auto_bucket() -> str:
    now = _time.monotonic()
    if _auto_cache["unit"] and now - _auto_cache["ts"] < _AUTO_TTL_S:
        return _auto_cache["unit"]
    rows = run_sql(
        f"""
        SELECT count(DISTINCT date_trunc('SECOND', request_time)) AS n_second,
               count(DISTINCT date_trunc('MINUTE', request_time)) AS n_minute,
               count(DISTINCT date_trunc('HOUR',   request_time)) AS n_hour
        FROM {settings.payload_fqn}
        """
    )
    r = rows[0] if rows else {}
    n_second = _num(r.get("n_second")) or 0
    n_minute = _num(r.get("n_minute")) or 0
    n_hour = _num(r.get("n_hour")) or 0

    if n_second and n_second <= _TARGET_POINTS:
        unit = "SECOND"
    elif n_minute and n_minute <= _TARGET_POINTS:
        unit = "MINUTE"
    elif n_hour and n_hour <= _TARGET_POINTS:
        unit = "HOUR"
    else:
        unit = "DAY"

    _auto_cache.update(unit=unit, ts=now)
    return unit


def _bucket_unit() -> str:
    """Bucket unit for the time series: an explicit config value, or auto-derived
    from the data's span when ``TIME_BUCKET`` is unset / ``AUTO``."""
    unit = (settings.time_bucket or "AUTO").upper()
    if unit in _VALID_BUCKETS:
        return unit
    return _auto_bucket()


# --------------------------------------------------------------------------- #
# GET /api/metrics  -- headline KPIs
# --------------------------------------------------------------------------- #
def get_kpis() -> dict[str, Any]:
    rows = run_sql(
        f"""
        SELECT count(*)                                                   AS total_requests,
               round(100.0 * sum(CASE WHEN status_code <> 200 THEN 1 ELSE 0 END)
                     / count(*), 3)                                       AS error_rate_pct,
               round(percentile(execution_duration_ms, 0.5), 1)          AS p50_ms,
               round(percentile(execution_duration_ms, 0.95), 1)         AS p95_ms,
               round(percentile(execution_duration_ms, 0.99), 1)         AS p99_ms,
               count(DISTINCT get_json_object(request, '{settings.patient_id_json_path}'))
                                                                          AS distinct_patients,
               min(request_time)                                         AS window_start,
               max(request_time)                                         AS window_end
        FROM {settings.payload_fqn}
        """
    )
    row = rows[0] if rows else {}
    return {
        "total_requests": _num(row.get("total_requests")) or 0,
        "error_rate_pct": _num(row.get("error_rate_pct")) or 0,
        "p50_ms": _num(row.get("p50_ms")),
        "p95_ms": _num(row.get("p95_ms")),
        "p99_ms": _num(row.get("p99_ms")),
        "distinct_patients": _num(row.get("distinct_patients")) or 0,
        "window_start": row.get("window_start"),
        "window_end": row.get("window_end"),
    }


# --------------------------------------------------------------------------- #
# GET /api/volume  -- request count per time bucket
# --------------------------------------------------------------------------- #
def get_volume() -> dict[str, Any]:
    unit = _bucket_unit()
    rows = run_sql(
        f"""
        SELECT date_trunc('{unit}', request_time) AS bucket,
               count(*)                            AS requests
        FROM {settings.payload_fqn}
        GROUP BY 1
        ORDER BY 1
        """
    )
    return {
        "bucket_unit": unit,
        "series": [
            {"bucket": r.get("bucket"), "requests": _num(r.get("requests")) or 0}
            for r in rows
        ],
    }


# --------------------------------------------------------------------------- #
# GET /api/latency  -- p50 / p95 latency per time bucket
# --------------------------------------------------------------------------- #
def get_latency() -> dict[str, Any]:
    unit = _bucket_unit()
    rows = run_sql(
        f"""
        SELECT date_trunc('{unit}', request_time)                 AS bucket,
               round(percentile(execution_duration_ms, 0.5), 1)   AS p50_ms,
               round(percentile(execution_duration_ms, 0.95), 1)  AS p95_ms
        FROM {settings.payload_fqn}
        GROUP BY 1
        ORDER BY 1
        """
    )
    return {
        "bucket_unit": unit,
        "series": [
            {
                "bucket": r.get("bucket"),
                "p50_ms": _num(r.get("p50_ms")),
                "p95_ms": _num(r.get("p95_ms")),
            }
            for r in rows
        ],
    }


# --------------------------------------------------------------------------- #
# GET /api/predictions  -- readmit (1) vs no-readmit (0) counts
# --------------------------------------------------------------------------- #
def get_predictions() -> list[dict[str, Any]]:
    rows = run_sql(
        f"""
        SELECT CAST(get_json_object(response, '$.predictions[0]') AS INT) AS prediction,
               count(*)                                                   AS count
        FROM {settings.payload_fqn}
        GROUP BY 1
        ORDER BY 1
        """
    )
    out = []
    for r in rows:
        pred = _num(r.get("prediction"))
        out.append(
            {
                "prediction": pred,
                "label": RISK_LABELS.get(pred, f"Class {pred}"),
                "count": _num(r.get("count")) or 0,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# GET /api/spans  -- latency broken down by OpenTelemetry span
# --------------------------------------------------------------------------- #
def get_spans() -> list[dict[str, Any]]:
    rows = run_sql(
        f"""
        SELECT name        AS span,
               count(*)     AS requests,
               round(avg(duration_ms), 2)                 AS avg_ms,
               round(percentile(duration_ms, 0.5), 2)     AS p50_ms,
               round(percentile(duration_ms, 0.95), 2)    AS p95_ms
        FROM (
            SELECT name,
                   (end_time_unix_nano - start_time_unix_nano) / 1e6 AS duration_ms
            FROM {settings.otel_fqn}
        )
        GROUP BY name
        ORDER BY avg_ms DESC
        """
    )
    return [
        {
            "span": r.get("span"),
            "label": SPAN_LABELS.get(r.get("span"), r.get("span")),
            "requests": _num(r.get("requests")) or 0,
            "avg_ms": _num(r.get("avg_ms")),
            "p50_ms": _num(r.get("p50_ms")),
            "p95_ms": _num(r.get("p95_ms")),
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# GET /api/recent  -- most recent requests
# --------------------------------------------------------------------------- #
def get_recent(limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    rows = run_sql(
        f"""
        SELECT request_time,
               CAST(get_json_object(request,  '{settings.patient_id_json_path}') AS INT) AS patient_id,
               CAST(get_json_object(response, '$.predictions[0]')                AS INT) AS prediction,
               execution_duration_ms                                                     AS latency_ms,
               status_code
        FROM {settings.payload_fqn}
        ORDER BY request_time DESC
        LIMIT {limit}
        """
    )
    out = []
    for r in rows:
        pred = _num(r.get("prediction"))
        out.append(
            {
                "request_time": r.get("request_time"),
                "patient_id": _num(r.get("patient_id")),
                "prediction": pred,
                "risk": "HIGH" if pred == 1 else "LOW" if pred == 0 else None,
                "latency_ms": _num(r.get("latency_ms")),
                "status_code": _num(r.get("status_code")),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Helper for the score panel's quick-pick chips (not a required endpoint).
# --------------------------------------------------------------------------- #
def get_sample_patients() -> dict[str, list[int]]:
    """A few real patient ids per predicted outcome, for the score panel's chips.

    Resilient: returns an empty mapping if the query fails so the panel still
    renders and remains usable with a manually typed id.
    """
    try:
        rows = run_sql(
            f"""
            SELECT prediction,
                   array_join(slice(array_sort(array_agg(DISTINCT pid)), 1, 4), ',') AS pids
            FROM (
                SELECT CAST(get_json_object(response, '$.predictions[0]')                AS INT) AS prediction,
                       CAST(get_json_object(request,  '{settings.patient_id_json_path}') AS INT) AS pid
                FROM {settings.payload_fqn}
            )
            WHERE pid IS NOT NULL
            GROUP BY prediction
            ORDER BY prediction
            """,
            timeout_s=30.0,
        )
    except Exception:
        return {}

    result: dict[str, list[int]] = {}
    for r in rows:
        pred = _num(r.get("prediction"))
        key = "low" if pred == 0 else "high" if pred == 1 else str(pred)
        pids = [int(x) for x in str(r.get("pids", "")).split(",") if x]
        if pids:
            result[key] = pids
    return result
