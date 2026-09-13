# PRTH Endpoint Monitor

A Databricks App that wraps the **PRTH 30-day readmission** model serving endpoint
and visualizes its inference/logging tables. Built for the PointClickCare MLOps
workshop.

Two things in one page:

1. **Score a patient** — calls the serving endpoint with just a patient key (the
   feature-store model does its own online feature lookup) and shows the predicted
   readmission risk (LOW / HIGH) plus the round-trip latency.
2. **Endpoint-performance dashboard** — reads the request-payload table and the
   OpenTelemetry span table through a SQL warehouse and renders KPI tiles, request
   volume over time, latency percentiles over time, the prediction mix, and a
   latency breakdown by span. The headline insight: the **online feature lookup
   dominates latency** (~74% of average per-request span time) versus model
   inference.

## Stack

- **Backend:** FastAPI (Python), `databricks-sdk` for both the serving-endpoint
  query and SQL warehouse statement execution. Serves the built React app as
  static files.
- **Frontend:** React + TypeScript + Vite, charts with Recharts.
- **Auth:** default Databricks SDK auth chain. Inside a Databricks App the platform
  injects the service-principal credentials; locally it uses a CLI profile.

## Layout

```
app/
├── app.yaml                  # Databricks App config (command + env)
├── app.py                    # FastAPI entry point; serves API + static SPA
├── requirements.txt          # Python deps
├── server/
│   ├── config.py             # env-driven settings (endpoint, warehouse, tables)
│   ├── databricks_client.py  # WorkspaceClient singleton, run_sql, score_patient
│   ├── metrics.py            # SQL queries for the dashboard
│   └── routes/
│       ├── score.py          # POST /api/score
│       └── metrics.py         # GET /api/metrics|volume|latency|predictions|spans|recent|config
└── frontend/
    ├── src/                  # React components (charts, score panel, KPI cards)
    └── dist/                 # built SPA (committed so the app deploys without Node)
```

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/score` | Body `{"patient_id": <int>}` → `{prediction, risk, latency_ms, ...}` |
| GET | `/api/metrics` | Headline KPIs (totals, error rate, p50/p95/p99, distinct patients) |
| GET | `/api/volume` | Request count per time bucket |
| GET | `/api/latency` | p50 / p95 latency per time bucket |
| GET | `/api/predictions` | Readmit (1) vs no-readmit (0) counts |
| GET | `/api/spans` | Latency broken down by OpenTelemetry span |
| GET | `/api/recent` | Most recent requests (`?limit=`, default 50) |
| GET | `/api/config` | Configured asset names + sample patient ids |
| GET | `/api/health` | Liveness probe |

## Configuration

Everything is configurable via environment variables (set in `app.yaml`) so the
app can be repointed without code changes. Defaults target the workshop assets.

| Env var | Default | Purpose |
|---------|---------|---------|
| `SERVING_ENDPOINT_NAME` | `prth-readmission-moe-abdelsamed` | Model serving endpoint to score against |
| `PATIENT_ID_KEY` | `patient_id` | Request field the model looks patients up by |
| `SQL_WAREHOUSE_ID` | `50c90044d2c0ab52` | Warehouse for dashboard queries |
| `TRACKING_CATALOG` | `pcc_mlops_demo_catalog` | Catalog of the tracking tables |
| `TRACKING_SCHEMA` | `moe_abdelsamed` | Schema of the tracking tables |
| `PAYLOAD_TABLE` | `prth_endpoint_tracking_payload` | Request/response payload table |
| `OTEL_SPANS_TABLE` | `prth_endpoint_tracking_otel_spans` | OpenTelemetry span table |
| `TIME_BUCKET` | `AUTO` | Volume/latency bucket; `AUTO` derives it from the data span, or pin `SECOND`/`MINUTE`/`HOUR`/`DAY` |

## Local development

Backend (uses a CLI profile for auth — real data loads):

```bash
cd app
DATABRICKS_PROFILE=<your-profile> \
  uv run --no-project --with-requirements requirements.txt \
  uvicorn app:app --host 127.0.0.1 --port 8000
```

Frontend dev server (proxies `/api` to :8000):

```bash
cd app/frontend
npm install
npm run dev      # http://localhost:5173
```

Production build (outputs to `frontend/dist`, which the backend serves):

```bash
cd app/frontend
npm run build
```

## Deploy

```bash
# 1. build the frontend (see above), then sync source to the workspace
databricks sync app /Workspace/Users/<you>/prth-endpoint-monitor --profile <profile>

# 2. create the app once
databricks apps create prth-endpoint-monitor --profile <profile>

# 3. deploy
databricks apps deploy prth-endpoint-monitor \
  --source-code-path /Workspace/Users/<you>/prth-endpoint-monitor --profile <profile>
```

## Permissions the app service principal needs

Attaching the endpoint and warehouse as app **resources** grants the SP CAN QUERY /
CAN USE automatically. The Unity Catalog table grants are explicit:

```bash
SP=<app service principal application id>   # from `databricks apps get <app>`

databricks grants update catalog pcc_mlops_demo_catalog \
  --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"USE_CATALOG\"]}]}"
databricks grants update schema pcc_mlops_demo_catalog.moe_abdelsamed \
  --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"USE_SCHEMA\"]}]}"
databricks grants update table pcc_mlops_demo_catalog.moe_abdelsamed.prth_endpoint_tracking_payload \
  --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"SELECT\"]}]}"
databricks grants update table pcc_mlops_demo_catalog.moe_abdelsamed.prth_endpoint_tracking_otel_spans \
  --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"SELECT\"]}]}"
```

To let others open the app, grant them **CAN USE** on the app itself
(Compute → Apps → prth-endpoint-monitor → Permissions).
