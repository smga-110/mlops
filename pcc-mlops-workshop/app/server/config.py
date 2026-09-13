"""Runtime configuration.

Every catalog / schema / table name, the serving endpoint, the SQL warehouse id,
and the request key are read from environment variables (set in ``app.yaml``) so
PointClickCare can repoint the app at their own assets without touching code. The
defaults below match the workshop assets in the PCC MLOps Deployment workspace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    """Read an env var, treating an empty string the same as unset."""
    value = os.environ.get(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    # --- Serving endpoint (Score-a-patient panel) ---
    endpoint_name: str = _env("SERVING_ENDPOINT_NAME", "prth-readmission-moe-abdelsamed")
    # The request field the feature-store model looks patients up by.
    patient_id_key: str = _env("PATIENT_ID_KEY", "patient_id")

    # --- SQL warehouse (dashboard queries) ---
    warehouse_id: str = _env("SQL_WAREHOUSE_ID", "50c90044d2c0ab52")

    # --- Inference / logging tables ---
    catalog: str = _env("TRACKING_CATALOG", "pcc_mlops_demo_catalog")
    schema: str = _env("TRACKING_SCHEMA", "moe_abdelsamed")
    payload_table: str = _env("PAYLOAD_TABLE", "prth_endpoint_tracking_payload")
    otel_table: str = _env("OTEL_SPANS_TABLE", "prth_endpoint_tracking_otel_spans")

    # Time bucket for the volume / latency series. "AUTO" (default) picks a bucket
    # from the data's actual time span (per-second for a short load-test burst,
    # up to per-day for weeks of traffic) so the charts always render with useful
    # resolution. PCC can pin it to SECOND / MINUTE / HOUR / DAY instead.
    time_bucket: str = _env("TIME_BUCKET", "AUTO")

    @property
    def payload_fqn(self) -> str:
        return f"{self.catalog}.{self.schema}.{self.payload_table}"

    @property
    def otel_fqn(self) -> str:
        return f"{self.catalog}.{self.schema}.{self.otel_table}"

    @property
    def patient_id_json_path(self) -> str:
        return f"$.dataframe_records[0].{self.patient_id_key}"


settings = Settings()

# True when running inside a Databricks App (service principal creds are injected).
IS_DATABRICKS_APP = bool(
    os.environ.get("DATABRICKS_APP_NAME") or os.environ.get("DATABRICKS_APP_URL")
)
