# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Load Testing & Inference Logging
# MAGIC
# MAGIC **Team: ML Engineering / Deployment (Workspace B)**
# MAGIC
# MAGIC The endpoint from notebook `03` is live. Before it carries production traffic, we want to know
# MAGIC **how it behaves under load** — latency at the tail, throughput per replica, where it starts to
# MAGIC saturate — and we want to see request/response traffic land in the **inference table** for
# MAGIC monitoring and drift analysis.
# MAGIC
# MAGIC This notebook:
# MAGIC 1. Sends a **warm-up** request (wakes a scale-to-zero endpoint) and validates the payload shape.
# MAGIC 2. Runs a **load test** across increasing concurrency, following the Databricks methodology
# MAGIC    ([Configure a load test](https://docs.databricks.com/aws/en/machine-learning/model-serving/configure-load-test)) —
# MAGIC    measure latency percentiles vs. concurrent connections, then read off the sizing you need.
# MAGIC 3. Confirms the **inference table** is populating with the requests we just sent.
# MAGIC
# MAGIC > **Prerequisite:** an **inference table is already enabled** on the endpoint (request/response
# MAGIC > logging). Set its full name in the `inference_table` widget below. Enabling it is a one-time
# MAGIC > endpoint config (Serving UI → *Inference tables*, or the AI Gateway API) — no model code changes.

# COMMAND ----------

# Package index: PCC's private Artifactory by default. For validation OUTSIDE PCC's network
# (where that host is unreachable), blank the `pip_index_url` widget to use public PyPI. `%pip`
# reads PIP_INDEX_URL from the environment, so we set it here — in the cell before the install.
import os

dbutils.widgets.text(
    "pip_index_url",
    "https://artifactory.pointclickcare.com/artifactory/api/pypi/pypi-virtual/simple/",
    "PyPI index URL (blank = public PyPI)",
)
_pip_index = dbutils.widgets.get("pip_index_url").strip()
if _pip_index:
    os.environ["PIP_INDEX_URL"] = _pip_index
    print(f"pip index: {_pip_index}")
else:
    os.environ.pop("PIP_INDEX_URL", None)
    print("pip index: public PyPI (default)")

# COMMAND ----------

# MAGIC %pip install --quiet databricks-sdk
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC Point at the endpoint (via the training team's catalog/schema, same as `03`) and at the
# MAGIC inference table you enabled. The load-test knobs are widgets so you can dial intensity up or down.

# COMMAND ----------

dbutils.widgets.text("catalog", "pcc_mlops_workshop", "Catalog (shared metastore)")
dbutils.widgets.text("schema", "", "Schema used by the training team (their derived schema)")
dbutils.widgets.text("inference_table", "", "Inference table (full name: catalog.schema.table)")
dbutils.widgets.text("concurrency_levels", "1,2,4,8", "Concurrency levels to sweep")
dbutils.widgets.text("seconds_per_level", "20", "Seconds of load per concurrency level")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA  = dbutils.widgets.get("schema").strip()
assert SCHEMA, "Set the 'schema' widget to the training team's schema (e.g. jane_doe)."

LABELS_TABLE    = f"{CATALOG}.{SCHEMA}.prth_labels"
ENDPOINT_NAME   = f"prth-readmission-{SCHEMA}".replace("_", "-")
PRIMARY_KEY     = "patient_id"
INFERENCE_TABLE = dbutils.widgets.get("inference_table").strip()

CONCURRENCY_LEVELS = [int(x) for x in dbutils.widgets.get("concurrency_levels").split(",") if x.strip()]
SECONDS_PER_LEVEL  = int(dbutils.widgets.get("seconds_per_level"))


def bq(fqn: str) -> str:
    """Backtick-quote each part of a dotted UC name for Spark / SQL (handles hyphens in the
    workspace-default catalog, e.g. `catalog-dbw-...`)."""
    return ".".join(f"`{part}`" for part in fqn.split("."))


print(f"Endpoint        : {ENDPOINT_NAME}")
print(f"Sample keys from: {LABELS_TABLE}")
print(f"Inference table : {INFERENCE_TABLE or '(set the widget)'}")
print(f"Load sweep      : concurrency {CONCURRENCY_LEVELS} × {SECONDS_PER_LEVEL}s each")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Sample payloads & warm-up
# MAGIC We pull real `patient_id`s to score, then send one request. The first request to a
# MAGIC **scale-to-zero** endpoint pays a cold-start penalty while a replica spins up — we do it here,
# MAGIC outside the timed run, so it doesn't skew the latency numbers.

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Real keys to cycle through (single-patient requests mimic real-time scoring)
sample_ids = [int(r[0]) for r in spark.table(bq(LABELS_TABLE)).select(PRIMARY_KEY).limit(100).collect()]
print(f"Loaded {len(sample_ids)} sample patient_ids")

# Warm-up: wake the endpoint and confirm the request/response shape
resp = w.serving_endpoints.query(name=ENDPOINT_NAME, dataframe_records=[{PRIMARY_KEY: sample_ids[0]}])
print(f"Warm-up OK · patient_id={sample_ids[0]} -> {resp.predictions}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Load test: latency vs. concurrency
# MAGIC The Databricks methodology: **hold the endpoint fixed and scale client-side concurrency**, then
# MAGIC watch how latency percentiles and throughput respond. Endpoint concurrency needed for a target
# MAGIC latency scales roughly linearly with concurrent connections, so this sweep tells you what
# MAGIC `workload_size` / provisioned concurrency you need for your expected RPS.
# MAGIC
# MAGIC Each worker thread sends requests back-to-back for the level's duration; we record every
# MAGIC request's latency, then summarize p50 / p90 / p99, throughput (RPS), and error rate.

# COMMAND ----------

import time
import concurrent.futures as cf
import numpy as np
import pandas as pd


def one_request(pid):
    """Send one single-patient request; return (latency_ms, ok)."""
    t0 = time.perf_counter()
    try:
        w.serving_endpoints.query(name=ENDPOINT_NAME, dataframe_records=[{PRIMARY_KEY: pid}])
        ok = True
    except Exception:
        ok = False
    return (time.perf_counter() - t0) * 1000.0, ok


def run_level(concurrency, seconds, ids):
    """Drive `concurrency` parallel clients for `seconds`; return summary stats."""
    stop_at = time.time() + seconds

    def worker(start_idx):
        out, i = [], start_idx
        while time.time() < stop_at:
            out.append(one_request(ids[i % len(ids)]))
            i += 1
        return out

    results = []
    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(worker, k) for k in range(concurrency)]
        for f in cf.as_completed(futures):
            results.extend(f.result())

    ok_latencies = [lat for lat, ok in results if ok]
    errors = sum(1 for _, ok in results if not ok)
    arr = np.array(ok_latencies) if ok_latencies else np.array([0.0])
    return {
        "concurrency": concurrency,
        "requests": len(results),
        "errors": errors,
        "error_rate": round(errors / max(len(results), 1), 3),
        "rps": round(len(results) / seconds, 1),
        "p50_ms": round(float(np.percentile(arr, 50)), 1),
        "p90_ms": round(float(np.percentile(arr, 90)), 1),
        "p99_ms": round(float(np.percentile(arr, 99)), 1),
    }


summary = []
for c in CONCURRENCY_LEVELS:
    print(f"→ load at concurrency={c} for {SECONDS_PER_LEVEL}s ...")
    summary.append(run_level(c, SECONDS_PER_LEVEL, sample_ids))

summary_df = pd.DataFrame(summary)
display(summary_df)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Reading the results
# MAGIC - **RPS should rise with concurrency** until the endpoint saturates; once p99 climbs steeply
# MAGIC   while RPS flattens, you've found the ceiling for this `workload_size`.
# MAGIC - Pick the concurrency whose **p99 still meets your SLA**, then surface the RPS at that point —
# MAGIC   that's your safe per-replica throughput. Scale `workload_size` / provisioned concurrency to
# MAGIC   cover your expected peak RPS.
# MAGIC - A non-zero **error_rate** under load usually means requests are being throttled/queued — a
# MAGIC   signal to scale up.
# MAGIC
# MAGIC #### Production-grade load testing (Locust)
# MAGIC For rigorous capacity planning Databricks recommends **Locust**, driven from the importable
# MAGIC [load-test notebook](https://docs.databricks.com/aws/en/machine-learning/model-serving/configure-load-test).
# MAGIC That harness uses a **service principal** (with `CAN QUERY`) whose token is stored in a **secret
# MAGIC scope**, an `input.json` payload file, and a `fast-load-test.py` helper — Locust can push
# MAGIC ~4000 requests/sec per core, far beyond an in-notebook thread pool. The thread-pool sweep above
# MAGIC is the lightweight, self-contained version for a workshop; the mechanics (scale concurrency →
# MAGIC read latency percentiles → size the endpoint) are identical.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Confirm the inference table is populating
# MAGIC Every request we just sent is logged **asynchronously** to the inference table (typically a few
# MAGIC minutes behind). We poll until rows appear, then parse the logged `request` / `response` JSON
# MAGIC back into `patient_id → prediction`. This table is the foundation for monitoring and drift
# MAGIC (Lakehouse Monitoring's `InferenceLog` profile reads exactly this).

# COMMAND ----------

assert INFERENCE_TABLE, "Set the 'inference_table' widget to your enabled inference table (catalog.schema.table)."

import time

rows = 0
for attempt in range(30):  # up to ~10 minutes
    try:
        rows = spark.table(bq(INFERENCE_TABLE)).count()
    except Exception as e:
        print(f"  table not queryable yet ({type(e).__name__}); logging may still be provisioning...")
        rows = 0
    if rows > 0:
        print(f"✅ inference table has {rows:,} rows")
        break
    print(f"  {rows} rows so far — inference logging is async (minutes). Waiting...")
    time.sleep(20)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Recent logged traffic
# MAGIC A raw look at the table, then the parsed key→prediction view.

# COMMAND ----------

df = spark.table(bq(INFERENCE_TABLE))
display(df.limit(10))

# COMMAND ----------

# Parse the standard inference-table request/response columns into key -> prediction.
# The `request` / `response` columns hold the JSON payloads; adjust the column names below if your
# enabled table uses a different schema.
try:
    parsed = df.selectExpr(
        f"get_json_object(request, '$.dataframe_records[0].{PRIMARY_KEY}') AS {PRIMARY_KEY}",
        "get_json_object(response, '$.predictions[0]') AS prediction",
    ).where("prediction IS NOT NULL").limit(25)
    display(parsed)
except Exception as e:
    print("Could not parse request/response columns — inspect the schema above and adjust:", e)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recap
# MAGIC - We drove real load at the endpoint and measured **p50/p90/p99 latency and throughput** across
# MAGIC   concurrency levels — the inputs to right-sizing a serving endpoint.
# MAGIC - Those requests flowed into the **inference table**, giving us a governed, queryable record of
# MAGIC   production traffic.
# MAGIC
# MAGIC ### Where this goes next
# MAGIC With the inference table populating, the monitoring loop closes:
# MAGIC - **Lakehouse Monitoring** (`InferenceLog` profile) over this table → auto-generated profile &
# MAGIC   drift metric tables + a quality dashboard.
# MAGIC - A **drift threshold → retraining job** (notebook `01`) wires up the full loop:
# MAGIC   **train → deploy → monitor → retrain.**
