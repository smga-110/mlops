# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy the PRTH Endpoint Monitor App
# MAGIC
# MAGIC **No local CLI needed** — run this notebook from anywhere in the workspace (it uses the
# MAGIC Databricks SDK, which is pre-installed). It deploys the app **directly from this git folder**,
# MAGIC so there's nothing to sync and no Node build step (the React bundle in `app/frontend/dist`
# MAGIC is committed).
# MAGIC
# MAGIC It will:
# MAGIC 1. Create the app (with its serving-endpoint + warehouse **resources**) if it doesn't exist.
# MAGIC 2. Grant the app's **service principal** read access to the two inference tracking tables.
# MAGIC 3. Deploy, wait for it to start, and print the URL.
# MAGIC
# MAGIC > **Prereqs:** you can create Databricks Apps in this workspace, you own (or can `MANAGE`) the
# MAGIC > tracking tables, and an **inference table is enabled** on the serving endpoint.
# MAGIC > Re-running is safe (idempotent) — it just redeploys.

# COMMAND ----------

# Package index: PCC's private Artifactory by default; blank the `pip_index_url` widget for public
# PyPI. `%pip` reads PIP_INDEX_URL from the environment, so we set it here before installing.
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

# MAGIC %pip install --upgrade --quiet databricks-sdk
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Settings
# MAGIC Defaults target the workshop assets — change these to your own endpoint / schema / warehouse.

# COMMAND ----------

dbutils.widgets.text("app_name", "", "App name (blank = derived from your email)")
dbutils.widgets.text("serving_endpoint_name", "prth-readmission-moe-abdelsamed", "Serving endpoint")
dbutils.widgets.text("sql_warehouse_id", "50c90044d2c0ab52", "SQL warehouse id")
dbutils.widgets.text("catalog", "pcc_mlops_demo_catalog", "Tracking catalog")
dbutils.widgets.text("schema", "moe_abdelsamed", "Tracking schema")
dbutils.widgets.text("payload_table", "prth_endpoint_tracking_payload", "Payload table")
dbutils.widgets.text("otel_spans_table", "prth_endpoint_tracking_otel_spans", "OTEL spans table")
dbutils.widgets.text("source_code_path", "", "App source path (blank = the app/ folder this notebook lives in)")

# App name: unique per user, derived from your email (like the schema in notebook 00) so
# attendees don't collide. App names allow only [a-z0-9-] and max 26 chars, so we slugify the
# email local-part (dots/underscores -> hyphens) and truncate. Override via the widget if desired.
import re
_email = spark.sql("SELECT current_user()").first()[0]
_slug = re.sub(r"[^a-z0-9]+", "-", _email.split("@")[0].lower()).strip("-")
APP_NAME  = dbutils.widgets.get("app_name").strip() or ("prth-mon-" + _slug)[:26].rstrip("-")
ENDPOINT  = dbutils.widgets.get("serving_endpoint_name").strip()
WAREHOUSE = dbutils.widgets.get("sql_warehouse_id").strip()
CATALOG   = dbutils.widgets.get("catalog").strip()
SCHEMA    = dbutils.widgets.get("schema").strip()
PAYLOAD   = dbutils.widgets.get("payload_table").strip()
SPANS     = dbutils.widgets.get("otel_spans_table").strip()

# Source = this notebook's own folder (the app/ dir) unless overridden. Deploying straight from
# the git folder means attendees just pull the repo and run this — nothing to upload.
import os
_nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
_dir = dbutils.widgets.get("source_code_path").strip() or os.path.dirname(_nb)
# The Apps API needs an absolute /Workspace-rooted path; notebookPath() returns "/Users/..." (no prefix).
SOURCE = _dir if _dir.startswith("/Workspace") else "/Workspace" + _dir

print(f"App        : {APP_NAME}")
print(f"Endpoint   : {ENDPOINT}")
print(f"Warehouse  : {WAREHOUSE}")
print(f"Tables     : {CATALOG}.{SCHEMA}.{PAYLOAD} , {SPANS}")
print(f"Source path: {SOURCE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy

# COMMAND ----------

import time
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def api(method, path, body=None):
    return w.api_client.do(method, path, body=body)


# 1. Create the app (with resources) if it doesn't exist. The resources auto-grant the app SP
#    CAN_QUERY on the endpoint and CAN_USE on the warehouse.
try:
    app = api("GET", f"/api/2.0/apps/{APP_NAME}")
    print(f"App '{APP_NAME}' already exists — will redeploy.")
except Exception:
    print(f"Creating app '{APP_NAME}' with endpoint + warehouse resources ...")
    api("POST", "/api/2.0/apps", {
        "name": APP_NAME,
        "description": "PRTH endpoint monitor — score patients and dashboard the inference tracking tables.",
        "resources": [
            {"name": "serving-endpoint", "serving_endpoint": {"name": ENDPOINT, "permission": "CAN_QUERY"}},
            {"name": "sql-warehouse", "sql_warehouse": {"id": WAREHOUSE, "permission": "CAN_USE"}},
        ],
    })

# 2. Wait for the app's service principal to exist.
sp = None
for _ in range(60):
    app = api("GET", f"/api/2.0/apps/{APP_NAME}")
    sp = app.get("service_principal_client_id")
    if sp:
        break
    time.sleep(5)
assert sp, "Timed out waiting for the app service principal."
print(f"App service principal: {sp}")

# 3. Grant the SP read access to the tracking tables (endpoint/warehouse are covered by resources).
def grant(securable_type, full_name, privileges):
    api("PATCH", f"/api/2.1/unity-catalog/permissions/{securable_type}/{full_name}",
        {"changes": [{"principal": sp, "add": privileges}]})

grant("catalog", CATALOG, ["USE_CATALOG"])
grant("schema", f"{CATALOG}.{SCHEMA}", ["USE_SCHEMA"])
grant("table", f"{CATALOG}.{SCHEMA}.{PAYLOAD}", ["SELECT"])
grant("table", f"{CATALOG}.{SCHEMA}.{SPANS}", ["SELECT"])
print("Granted USE CATALOG / USE SCHEMA / SELECT (x2) to the app SP.")

# 4. Make sure the app compute is RUNNING before deploying. A freshly CREATED app hasn't started
#    yet, and deploying a non-running app fails with "not in RUNNING state. Please start the app first."
def compute_state():
    return (api("GET", f"/api/2.0/apps/{APP_NAME}").get("compute_status") or {}).get("state")

cstate = compute_state()
if cstate in (None, "STOPPED"):
    print("Starting app compute…")
    try:
        api("POST", f"/api/2.0/apps/{APP_NAME}/start")
    except Exception as e:
        print("  start:", e)
for _ in range(90):  # first-time compute provisioning can take several minutes
    cstate = compute_state()
    print(f"  compute: {cstate}")
    if cstate == "ACTIVE":
        break
    if cstate == "STOPPED":
        try:
            api("POST", f"/api/2.0/apps/{APP_NAME}/start")
        except Exception:
            pass
    time.sleep(10)
assert cstate == "ACTIVE", f"App compute did not reach ACTIVE (state={cstate}); cannot deploy."

# 5. Deploy from the workspace source path and wait for it to finish.
print(f"Deploying from {SOURCE} ...")
dep = api("POST", f"/api/2.0/apps/{APP_NAME}/deployments",
          {"source_code_path": SOURCE, "mode": "SNAPSHOT"})
dep_id = dep["deployment_id"]

state = None
for _ in range(90):  # up to ~15 min
    d = api("GET", f"/api/2.0/apps/{APP_NAME}/deployments/{dep_id}")
    state = d.get("status", {}).get("state")
    print(f"  deployment: {state}")
    if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
        break
    time.sleep(10)

app = api("GET", f"/api/2.0/apps/{APP_NAME}")
print("\n" + ("=" * 60))
if state == "SUCCEEDED":
    print(f"✅ Deployed: {app.get('url')}")
else:
    print(f"⚠️  Deployment ended in state {state}: {d.get('status', {}).get('message')}")
print("=" * 60)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Let attendees open the app
# MAGIC By default only the creator + workspace admins can open the app. Grant others **CAN USE**:
# MAGIC **Compute → Apps → your app → Permissions**, or run the cell below with a group/user name.

# COMMAND ----------

# GRANT_TO = "your-workshop-group"   # <- set a group or user, then run this cell
# api("PATCH", f"/api/2.0/permissions/apps/{APP_NAME}",
#     {"access_control_list": [{"group_name": GRANT_TO, "permission_level": "CAN_USE"}]})
# print(f"Granted CAN_USE on {APP_NAME} to {GRANT_TO}")
