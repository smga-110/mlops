# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Model Deployment — Cross-Workspace Handoff & Serving
# MAGIC
# MAGIC **Team: ML Engineering / Deployment (Workspace B)**
# MAGIC
# MAGIC > 🔁 **This notebook runs in a *different workspace* than `01`/`02`.** PCC's training team and
# MAGIC > deployment team work in separate workspaces that share **one Unity Catalog metastore**. Because
# MAGIC > the model and feature table are **governed UC objects**, the deployment team never needs a copy
# MAGIC > of the code, the artifacts, or the training data — they just need the right **UC privileges**.
# MAGIC
# MAGIC What this notebook shows:
# MAGIC 1. **The handoff** — exactly which grants the training team runs so the deployment team (and the
# MAGIC    serving endpoint) can use the model and its features.
# MAGIC 2. **Online store publish** — materialize the feature table to a **Lakebase online store** so
# MAGIC    features can be looked up in real time.
# MAGIC 3. **Real-time serving** — deploy the UC model to a **Model Serving endpoint** and score a patient
# MAGIC    by **`patient_id` alone** (features fetched automatically online).
# MAGIC 4. Recap of **offline/batch** lookup (already shown in `02`) — the same model, both modes.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-feature-engineering==0.13.0.1 "mlflow>=3.8.1" databricks-sdk
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Config
# MAGIC In Workspace B we don't `%run` the training team's setup notebook — instead we point at the
# MAGIC **same UC objects** by name. Set the catalog/schema to match what the training team used
# MAGIC (their derived schema). Everything else is a governed UC reference.

# COMMAND ----------

dbutils.widgets.text("catalog", "pcc_mlops_workshop", "Catalog (shared metastore)")
dbutils.widgets.text("schema", "", "Schema used by the training team (their derived schema)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA  = dbutils.widgets.get("schema").strip()
assert SCHEMA, "Set the 'schema' widget to the training team's schema (e.g. jane_doe)."

FEATURE_TABLE = f"{CATALOG}.{SCHEMA}.prth_patient_features"
LABELS_TABLE  = f"{CATALOG}.{SCHEMA}.prth_labels"
MODEL_NAME    = f"{CATALOG}.{SCHEMA}.prth_readmission_lgbm"
PRIMARY_KEY   = "patient_id"
ENDPOINT_NAME = f"prth-readmission-{SCHEMA}".replace("_", "-")
ONLINE_STORE  = f"prth-online-{SCHEMA}".replace("_", "-")          # Lakebase online store (instance) name
ONLINE_TABLE  = f"{CATALOG}.{SCHEMA}.prth_patient_features_online"  # published online copy of the feature table


def bq(fqn: str) -> str:
    """Backtick-quote each part of a dotted UC name for Spark / SQL (handles hyphens etc. in
    catalog names, e.g. the workspace-default `catalog-dbw-...`). Do NOT use for the Feature
    Engineering client, MLflow model names, or `models:/` URIs — those take the raw name."""
    return ".".join(f"`{part}`" for part in fqn.split("."))

print(f"Model         : {MODEL_NAME}")
print(f"Feature table : {FEATURE_TABLE}")
print(f"Endpoint      : {ENDPOINT_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — The cross-workspace handoff (grants)
# MAGIC These `GRANT`s are run **by the training team (Workspace A)** — the owners of the model and
# MAGIC feature table. Because grants live in the **metastore**, they take effect in **every** workspace
# MAGIC attached to it, including Workspace B. This is the entire handoff: no artifact copy, no export.
# MAGIC
# MAGIC The deployment **principal** (the human or service principal creating the endpoint) needs:
# MAGIC - `USE CATALOG`, `USE SCHEMA`
# MAGIC - `EXECUTE` on the model (this is what grants access to the model *artifacts* — no separate access needed)
# MAGIC - `SELECT` on the feature table (to publish it online)
# MAGIC
# MAGIC > Replace `deployment_team` with the actual UC group / service principal. Run these **in Workspace A**
# MAGIC > (or here, if you have MANAGE on the objects). They're shown as SQL so PCC can lift them verbatim.

# COMMAND ----------

# MAGIC %md
# MAGIC ```sql
# MAGIC -- === Run by the TRAINING TEAM (owners) in Workspace A ===
# MAGIC GRANT USE CATALOG ON CATALOG pcc_mlops_workshop                       TO `deployment_team`;
# MAGIC GRANT USE SCHEMA  ON SCHEMA  pcc_mlops_workshop.jane_doe              TO `deployment_team`;
# MAGIC GRANT EXECUTE     ON MODEL   pcc_mlops_workshop.jane_doe.prth_readmission_lgbm TO `deployment_team`;
# MAGIC GRANT SELECT      ON TABLE   pcc_mlops_workshop.jane_doe.prth_patient_features TO `deployment_team`;
# MAGIC ```
# MAGIC
# MAGIC **What the deployment team does NOT need:** access to the training notebooks, the raw dataset,
# MAGIC MLflow experiment write access, or any storage credential. `EXECUTE ON MODEL` + `USE` on the
# MAGIC namespace is the complete surface for standing up a serving endpoint.

# COMMAND ----------

# MAGIC %md
# MAGIC ### Verify the handoff worked
# MAGIC From Workspace B, confirm we can *see* the governed objects the training team registered. If
# MAGIC these succeed, the grants are in place and the metastore is shared correctly.

# COMMAND ----------

from mlflow.tracking import MlflowClient
import mlflow

mlflow.set_registry_uri("databricks-uc")
client = MlflowClient()

model_version = client.get_model_version_by_alias(MODEL_NAME, "prod")
print(f"✅ Can see model {MODEL_NAME} @prod -> v{model_version.version}")
print(f"✅ Can read feature table: {spark.table(bq(FEATURE_TABLE)).count():,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Publish the feature table to a Lakebase online store
# MAGIC Offline `score_batch` reads features from the Delta table. **Real-time** serving needs them in a
# MAGIC **low-latency online store** — Databricks' managed **Lakebase** online store. Publishing keeps
# MAGIC the online copy in sync with the offline feature table.
# MAGIC
# MAGIC > **Re-run caveat:** the published online table is linked to the offline feature table by its
# MAGIC > internal `table_id`. If you ever **re-run notebook 02** (which drops & recreates the feature
# MAGIC > table), that link goes stale and serving fails with *"No suitable online store found"*. If that
# MAGIC > happens, run the **reset cell below** once, then continue. On a first, clean run you can skip it.

# COMMAND ----------

from databricks.feature_engineering import FeatureEngineeringClient
from databricks.sdk import WorkspaceClient

fe = FeatureEngineeringClient()

# --- OPTIONAL RESET (uncomment only if you re-ran notebook 02 and now hit a stale-link error) ---
# Removes the old online store and the orphaned synced online table so the publish below
# re-links to the current feature table. Safe to leave commented on a clean first run.
#
# try:
#     fe.delete_online_store(name=ONLINE_STORE)
# except Exception as e:
#     print("no existing online store to delete:", e)
# try:
#     WorkspaceClient().database.delete_synced_database_table(ONLINE_TABLE)
# except Exception as e:
#     print("no orphaned synced table to drop:", e)

# 2a. Provision (or reuse) a Databricks online store — a managed, Lakebase-backed,
#     low-latency store. This spins up an autoscaling Lakebase instance (takes a few minutes).
#     Note: get_online_store returns None (not an error) when the store doesn't exist yet.
online_store = fe.get_online_store(name=ONLINE_STORE)
if online_store is None:
    online_store = fe.create_online_store(
        name=ONLINE_STORE,
        capacity="CU_1",          # smallest capacity unit; CU_1/CU_2/CU_4/CU_8
    )
    print(f"Created online store {ONLINE_STORE}")
else:
    print(f"Reusing existing online store {ONLINE_STORE}")

# 2a-wait. The online store provisions a Lakebase instance asynchronously — wait for AVAILABLE
#         before publishing (the serving layer can't use a store that isn't ready).
import time
state = "PENDING"
for _ in range(60):
    os_obj = fe.get_online_store(name=ONLINE_STORE)
    state = str(os_obj.state) if os_obj is not None else "PENDING"
    if "AVAILABLE" in state:
        break
    print(f"  online store state = {state} ... waiting")
    time.sleep(20)
print(f"Online store {ONLINE_STORE} is {state}")

# 2b. Publish the offline feature table into the online store. TRIGGERED keeps the online
#     copy in sync from the feature table's Change Data Feed (enabled in notebook 02).
fe.publish_table(
    source_table_name=FEATURE_TABLE,
    online_table_name=ONLINE_TABLE,
    online_store=online_store,
    publish_mode="TRIGGERED",
)
print(f"Published {FEATURE_TABLE} -> {ONLINE_TABLE} (online).")

# 2b-wait. TRIGGERED publish syncs asynchronously. Wait until the online table is fully online
#         so the serving endpoint can discover it during feature-lookup setup.
for _ in range(60):
    detailed = WorkspaceClient().database.get_synced_database_table(
        ONLINE_TABLE
    ).data_synchronization_status.detailed_state
    if "ONLINE_NO_PENDING_UPDATE" in str(detailed):
        break
    print(f"  synced table state = {detailed} ... waiting")
    time.sleep(20)
print(f"Online table {ONLINE_TABLE} is {detailed}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Deploy the model to a real-time Model Serving endpoint
# MAGIC We serve the **`@prod`** version — the feature-store-packaged model from notebook `02`. Because
# MAGIC the feature-lookup metadata travels with the model, the endpoint knows to fetch features from the
# MAGIC online store at request time. The endpoint's runtime identity inherits the same UC grants.

# COMMAND ----------

from datetime import timedelta
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput

w = WorkspaceClient()

# First-time serving deployments build a container and wire up the online feature lookup,
# which can take 15-30 minutes. Give the waiter enough headroom.
DEPLOY_TIMEOUT = timedelta(minutes=45)

served = ServedEntityInput(
    entity_name=MODEL_NAME,
    entity_version=model_version.version,
    workload_size="Small",             # "Small" | "Medium" | "Large"
    scale_to_zero_enabled=True,
)

existing = [e.name for e in w.serving_endpoints.list()]
if ENDPOINT_NAME in existing:
    print(f"Updating existing endpoint {ENDPOINT_NAME} ...")
    w.serving_endpoints.update_config_and_wait(
        name=ENDPOINT_NAME, served_entities=[served], timeout=DEPLOY_TIMEOUT,
    )
else:
    print(f"Creating endpoint {ENDPOINT_NAME} (first deploy can take 15-30 min) ...")
    w.serving_endpoints.create_and_wait(
        name=ENDPOINT_NAME,
        config=EndpointCoreConfigInput(name=ENDPOINT_NAME, served_entities=[served]),
        timeout=DEPLOY_TIMEOUT,
    )
print(f"✅ Endpoint {ENDPOINT_NAME} ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Real-time scoring by key only
# MAGIC The moment of truth: we send **just a `patient_id`**. The endpoint looks the features up from
# MAGIC the online store and returns a prediction — no feature values in the request payload.

# COMMAND ----------

sample_ids = [int(r[0]) for r in spark.table(bq(LABELS_TABLE)).select(PRIMARY_KEY).limit(3).collect()]

response = w.serving_endpoints.query(
    name=ENDPOINT_NAME,
    dataframe_records=[{PRIMARY_KEY: pid} for pid in sample_ids],
)
print("Real-time predictions (features fetched automatically online):")
for pid, pred in zip(sample_ids, response.predictions):
    print(f"  patient_id={pid}  ->  {pred}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Recap — one model, two lookup modes
# MAGIC | Use case | Where | How it's called | Feature source |
# MAGIC |---|---|---|---|
# MAGIC | **Batch scoring** | Notebook / job (`02`) | `fe.score_batch(model_uri, df_of_keys)` | Offline Delta feature table |
# MAGIC | **Real-time** | Serving endpoint (`03`) | `POST` `{patient_id}` | Lakebase online store |
# MAGIC
# MAGIC The **same registered UC model** powers both — that's the payoff of packaging it with
# MAGIC `fe.log_model` and automatic feature lookup.
# MAGIC
# MAGIC ✅ **Deployed.** Next: **`04_monitoring`** to turn on inference logging and drift dashboards.
