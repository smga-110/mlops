#!/usr/bin/env bash
#
# Deploy the PRTH Endpoint Monitor Databricks App.
#
# One command: syncs this app/ folder to the workspace, creates the app (with its
# serving-endpoint + warehouse resources) if needed, grants the app's service principal
# read access to the tracking tables, and deploys. Safe to re-run (idempotent).
#
# Usage:
#   ./deploy.sh                          # uses the workshop defaults below
#   PROFILE=my-cli-profile ./deploy.sh   # override any setting via env var
#   BUILD=1 ./deploy.sh                  # rebuild the React frontend first (needs Node)
#
# Prereqs: Databricks CLI authenticated (`databricks auth login --profile <PROFILE>`),
#          and an inference table already enabled on the serving endpoint.
set -euo pipefail

# ---- Config (override any of these via environment variables) ----------------------
PROFILE="${PROFILE:-pcc-mlops-deploy}"
APP_NAME="${APP_NAME:-prth-endpoint-monitor}"
SERVING_ENDPOINT_NAME="${SERVING_ENDPOINT_NAME:-prth-readmission-moe-abdelsamed}"
SQL_WAREHOUSE_ID="${SQL_WAREHOUSE_ID:-50c90044d2c0ab52}"
TRACKING_CATALOG="${TRACKING_CATALOG:-pcc_mlops_demo_catalog}"
TRACKING_SCHEMA="${TRACKING_SCHEMA:-moe_abdelsamed}"
PAYLOAD_TABLE="${PAYLOAD_TABLE:-prth_endpoint_tracking_payload}"
OTEL_SPANS_TABLE="${OTEL_SPANS_TABLE:-prth_endpoint_tracking_otel_spans}"
BUILD="${BUILD:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
db() { databricks "$@" --profile "$PROFILE"; }

echo "▸ Profile=$PROFILE  App=$APP_NAME"

USER_EMAIL="$(db current-user me --output json | python3 -c 'import sys,json;print(json.load(sys.stdin)["userName"])')"
# Workspace staging path the app is deployed from (decoupled from your git checkout).
SOURCE_PATH="${SOURCE_PATH:-/Workspace/Users/${USER_EMAIL}/apps/${APP_NAME}}"

# ---- 1. (optional) build the React frontend -----------------------------------------
if [ "$BUILD" = "1" ]; then
  echo "▸ Building frontend (npm install && npm run build)…"
  ( cd "$SCRIPT_DIR/frontend" && npm install && npm run build )
fi
if [ ! -f "$SCRIPT_DIR/frontend/dist/index.html" ]; then
  echo "ERROR: frontend/dist/index.html not found. Commit the built SPA, or run with BUILD=1." >&2
  exit 1
fi

# ---- 2. sync source to the workspace ------------------------------------------------
echo "▸ Syncing app source → $SOURCE_PATH"
db sync "$SCRIPT_DIR" "$SOURCE_PATH" --full

# ---- 3. create the app (with resources) if it doesn't exist -------------------------
if db apps get "$APP_NAME" >/dev/null 2>&1; then
  echo "▸ App exists — skipping create."
else
  echo "▸ Creating app with serving-endpoint + warehouse resources…"
  cat > /tmp/${APP_NAME}_create.json <<JSON
{
  "description": "PRTH endpoint monitor — score patients and dashboard the inference tracking tables.",
  "resources": [
    {"name": "serving-endpoint", "serving_endpoint": {"name": "$SERVING_ENDPOINT_NAME", "permission": "CAN_QUERY"}},
    {"name": "sql-warehouse", "sql_warehouse": {"id": "$SQL_WAREHOUSE_ID", "permission": "CAN_USE"}}
  ]
}
JSON
  db apps create "$APP_NAME" --json "@/tmp/${APP_NAME}_create.json"
fi

# ---- 4. wait for the app's service principal, then grant table access ---------------
echo "▸ Waiting for the app service principal…"
SP=""
for _ in $(seq 1 30); do
  SP="$(db apps get "$APP_NAME" --output json 2>/dev/null | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("service_principal_client_id",""))
except Exception: print("")')"
  [ -n "$SP" ] && break
  sleep 5
done
[ -z "$SP" ] && { echo "ERROR: could not resolve the app service principal." >&2; exit 1; }
echo "▸ App SP client id: $SP"

echo "▸ Granting the app SP read access to the tracking tables…"
db grants update catalog "$TRACKING_CATALOG" \
  --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"USE_CATALOG\"]}]}" >/dev/null
db grants update schema "$TRACKING_CATALOG.$TRACKING_SCHEMA" \
  --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"USE_SCHEMA\"]}]}" >/dev/null
for T in "$PAYLOAD_TABLE" "$OTEL_SPANS_TABLE"; do
  db grants update table "$TRACKING_CATALOG.$TRACKING_SCHEMA.$T" \
    --json "{\"changes\":[{\"principal\":\"$SP\",\"add\":[\"SELECT\"]}]}" >/dev/null
done
# (The serving endpoint CAN_QUERY and warehouse CAN_USE are granted automatically via the
#  app resources declared above — no extra permission calls needed.)

# ---- 4b. ensure the app compute is RUNNING before deploying -------------------------
# A freshly created app hasn't started yet; deploying it fails with "not in RUNNING state".
cstate() { db apps get "$APP_NAME" --output json | python3 -c 'import sys,json;print((json.load(sys.stdin).get("compute_status") or {}).get("state",""))'; }
CS="$(cstate)"
if [ "$CS" != "ACTIVE" ]; then
  echo "▸ Starting app compute (state=$CS)…"
  db apps start "$APP_NAME" >/dev/null 2>&1 || true
  for _ in $(seq 1 90); do
    CS="$(cstate)"; echo "  compute: $CS"
    [ "$CS" = "ACTIVE" ] && break
    sleep 10
  done
fi
[ "$CS" = "ACTIVE" ] || { echo "ERROR: app compute did not reach ACTIVE (state=$CS)." >&2; exit 1; }

# ---- 5. deploy ----------------------------------------------------------------------
echo "▸ Deploying…"
db apps deploy "$APP_NAME" --source-code-path "$SOURCE_PATH" --mode SNAPSHOT

URL="$(db apps get "$APP_NAME" --output json | python3 -c 'import sys,json;print(json.load(sys.stdin).get("url",""))')"
echo ""
echo "✅ Deployed: $URL"
echo "ℹ️  To let workshop attendees open it: Compute → Apps → $APP_NAME → Permissions → add them with CAN USE."
