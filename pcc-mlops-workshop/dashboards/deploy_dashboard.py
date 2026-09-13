#!/usr/bin/env python3
"""
Create the **PRTH Endpoint Monitoring** AI/BI (Lakeview) dashboard from code.

It reads the two inference/logging tables that Model Serving writes when you enable an
inference table on the endpoint:
  - <catalog>.<schema>.prth_endpoint_tracking_payload     (one row per request)
  - <catalog>.<schema>.prth_endpoint_tracking_otel_spans  (OpenTelemetry spans, 2 per request)

Usage
-----
  python deploy_dashboard.py \
      --catalog pcc_mlops_demo_catalog \
      --schema  moe_abdelsamed \
      --warehouse-id 50c90044d2c0ab52 \
      --profile pcc-mlops-deploy \
      [--parent-path /Users/you@company.com] \
      [--name "PRTH Endpoint Monitoring"] \
      [--publish] [--dump prth_endpoint_monitoring.lvdash.json]

Notes
-----
- The table names default to the `prth_endpoint_tracking_*` convention. If you named your
  inference table differently, pass --payload-table / --spans-table (unqualified names).
- --dump writes the serialized dashboard with {{CATALOG}}/{{SCHEMA}} placeholders so you can
  commit a reusable template to the repo.
"""
import argparse, json, subprocess, sys, tempfile, os

CAT, SCH = "{{CATALOG}}", "{{SCHEMA}}"


def build(payload_tbl: str, spans_tbl: str) -> dict:
    PAY = f"{CAT}.{SCH}.{payload_tbl}"
    SPN = f"{CAT}.{SCH}.{spans_tbl}"

    datasets = [
        {"name": "ds_summary", "displayName": "Summary", "queryLines": [
            "SELECT count(*) AS total_requests, "
            "round(sum(CASE WHEN status_code <> 200 THEN 1 ELSE 0 END)/count(*), 4) AS error_rate, "
            "round(approx_percentile(execution_duration_ms, 0.5), 1) AS p50_ms, "
            "round(approx_percentile(execution_duration_ms, 0.95), 1) AS p95_ms, "
            "round(approx_percentile(execution_duration_ms, 0.99), 1) AS p99_ms, "
            "count(DISTINCT get_json_object(request, '$.dataframe_records[0].patient_id')) AS distinct_patients "
            f"FROM {PAY}"]},
        {"name": "ds_volume", "displayName": "Request volume", "queryLines": [
            "SELECT date_trunc('SECOND', request_time) AS ts, count(*) AS requests "
            f"FROM {PAY} GROUP BY 1 ORDER BY 1"]},
        {"name": "ds_latency", "displayName": "Latency over time", "queryLines": [
            "SELECT date_trunc('SECOND', request_time) AS ts, "
            "round(approx_percentile(execution_duration_ms, 0.5), 1) AS p50_ms, "
            "round(approx_percentile(execution_duration_ms, 0.95), 1) AS p95_ms "
            f"FROM {PAY} GROUP BY 1 ORDER BY 1"]},
        {"name": "ds_pred", "displayName": "Prediction mix", "queryLines": [
            "SELECT CASE WHEN get_json_object(response, '$.predictions[0]') = '1' "
            "THEN 'Readmit (HIGH)' ELSE 'No readmit (LOW)' END AS prediction, count(*) AS requests "
            f"FROM {PAY} GROUP BY 1"]},
        {"name": "ds_span", "displayName": "Latency by span", "queryLines": [
            "SELECT name AS span, "
            "round(approx_percentile((end_time_unix_nano - start_time_unix_nano)/1e6, 0.5), 2) AS p50_ms, "
            "round(approx_percentile((end_time_unix_nano - start_time_unix_nano)/1e6, 0.95), 2) AS p95_ms "
            f"FROM {SPN} GROUP BY name ORDER BY p50_ms DESC"]},
        {"name": "ds_recent", "displayName": "Recent requests", "queryLines": [
            "SELECT date_format(request_time, 'yyyy-MM-dd HH:mm:ss') AS request_time, "
            "get_json_object(request, '$.dataframe_records[0].patient_id') AS patient_id, "
            "get_json_object(response, '$.predictions[0]') AS prediction, "
            "execution_duration_ms, status_code "
            f"FROM {PAY} ORDER BY request_time DESC LIMIT 100"]},
    ]

    def text(name, md, x, y, w, h):
        return {"widget": {"name": name, "multilineTextboxSpec": {"lines": [md]}},
                "position": {"x": x, "y": y, "width": w, "height": h}}

    def counter(name, col, title, x, y, w=2, h=3):
        return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
            "datasetName": "ds_summary", "fields": [{"name": col, "expression": f"`{col}`"}],
            "disaggregated": True}}],
            "spec": {"version": 2, "widgetType": "counter",
                     "encodings": {"value": {"fieldName": col, "displayName": title}},
                     "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}

    def line(name, ds, xcol, yfields, title, x, y, w, h):
        fields = [{"name": xcol, "expression": f"`{xcol}`"}]
        yenc = []
        for col, disp in yfields:
            fields.append({"name": f"sum({col})", "expression": f"SUM(`{col}`)"})
            yenc.append({"fieldName": f"sum({col})", "displayName": disp})
        return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
            "datasetName": ds, "fields": fields, "disaggregated": False}}],
            "spec": {"version": 3, "widgetType": "line",
                     "encodings": {"x": {"fieldName": xcol, "scale": {"type": "temporal"}, "displayName": "Time"},
                                   "y": {"scale": {"type": "quantitative"}, "fields": yenc}},
                     "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}

    def bar(name, ds, xcol, yfields, title, x, y, w, h):
        fields = [{"name": xcol, "expression": f"`{xcol}`"}]
        yenc = []
        for col, disp in yfields:
            fields.append({"name": f"sum({col})", "expression": f"SUM(`{col}`)"})
            yenc.append({"fieldName": f"sum({col})", "displayName": disp})
        return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
            "datasetName": ds, "fields": fields, "disaggregated": False}}],
            "spec": {"version": 3, "widgetType": "bar",
                     "encodings": {"x": {"fieldName": xcol, "scale": {"type": "categorical"}, "displayName": "Span"},
                                   "y": {"scale": {"type": "quantitative"}, "fields": yenc},
                                   "label": {"show": True}},
                     "mark": {"layout": "group", "colors": ["#FFAB00", "#FF3621"]},
                     "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}

    def pie(name, ds, angle_col, color_col, title, x, y, w, h):
        return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
            "datasetName": ds, "fields": [
                {"name": f"sum({angle_col})", "expression": f"SUM(`{angle_col}`)"},
                {"name": color_col, "expression": f"`{color_col}`"}], "disaggregated": False}}],
            "spec": {"version": 3, "widgetType": "pie",
                     "encodings": {"angle": {"fieldName": f"sum({angle_col})", "scale": {"type": "quantitative"}, "displayName": "Requests"},
                                   "color": {"fieldName": color_col, "scale": {"type": "categorical",
                                             "mappings": [{"value": "Readmit (HIGH)", "color": "#FF3621"},
                                                          {"value": "No readmit (LOW)", "color": "#00A972"}]}, "displayName": "Prediction"}},
                     "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}

    def table(name, ds, cols, title, x, y, w, h):
        fields = [{"name": c, "expression": f"`{c}`"} for c, _ in cols]
        columns = [{"fieldName": c, "displayName": d} for c, d in cols]
        return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
            "datasetName": ds, "fields": fields, "disaggregated": True}}],
            "spec": {"version": 2, "widgetType": "table", "encodings": {"columns": columns},
                     "frame": {"showTitle": True, "title": title}}},
            "position": {"x": x, "y": y, "width": w, "height": h}}

    layout = [
        text("title", "## PRTH Endpoint Monitoring", 0, 0, 6, 1),
        text("subtitle", "Real-time readmission endpoint — traffic, latency, and where the milliseconds go. Source: inference & OTEL-span logging tables.", 0, 1, 6, 1),
        # KPI row 1
        counter("kpi-total", "total_requests", "Total requests", 0, 2),
        counter("kpi-patients", "distinct_patients", "Distinct patients", 2, 2),
        counter("kpi-error", "error_rate", "Error rate", 4, 2),
        # KPI row 2
        counter("kpi-p50", "p50_ms", "Latency p50 (ms)", 0, 5),
        counter("kpi-p95", "p95_ms", "Latency p95 (ms)", 2, 5),
        counter("kpi-p99", "p99_ms", "Latency p99 (ms)", 4, 5),
        # Latency section
        text("hdr-latency", "### Latency breakdown — where the milliseconds go", 0, 8, 6, 1),
        bar("span-latency", "ds_span", "span", [("p50_ms", "p50 (ms)"), ("p95_ms", "p95 (ms)")],
            "Latency by span (feature lookup vs. model)", 0, 9, 3, 6),
        line("latency-ts", "ds_latency", "ts", [("p50_ms", "p50 (ms)"), ("p95_ms", "p95 (ms)")],
             "Latency percentiles over time", 3, 9, 3, 6),
        # Traffic section
        text("hdr-traffic", "### Traffic & predictions", 0, 15, 6, 1),
        line("volume-ts", "ds_volume", "ts", [("requests", "Requests")], "Request volume over time", 0, 16, 3, 6),
        pie("pred-mix", "ds_pred", "requests", "prediction", "Prediction mix (readmit vs. not)", 3, 16, 3, 6),
        # Detail
        text("hdr-recent", "### Recent requests", 0, 22, 6, 1),
        table("recent", "ds_recent", [("request_time", "Request time"), ("patient_id", "Patient ID"),
              ("prediction", "Prediction"), ("execution_duration_ms", "Latency (ms)"), ("status_code", "Status")],
              "Recent requests (last 100)", 0, 23, 6, 7),
    ]

    return {"datasets": datasets,
            "pages": [{"name": "overview", "displayName": "Overview", "pageType": "PAGE_TYPE_CANVAS", "layout": layout}],
            "uiSettings": {"theme": {"widgetHeaderAlignment": "ALIGNMENT_UNSPECIFIED"}}}


def cli(args_list):
    r = subprocess.run(["databricks"] + args_list, capture_output=True, text=True)
    return r.stdout, r.stderr, r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--warehouse-id", required=True)
    ap.add_argument("--profile", default="DEFAULT")
    ap.add_argument("--parent-path", default=None, help="Workspace folder for the dashboard (default: your home)")
    ap.add_argument("--name", default="PRTH Endpoint Monitoring")
    ap.add_argument("--payload-table", default="prth_endpoint_tracking_payload")
    ap.add_argument("--spans-table", default="prth_endpoint_tracking_otel_spans")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--dump", default=None, help="Write the serialized template (with {{CATALOG}}/{{SCHEMA}}) to this file")
    ap.add_argument("--no-create", action="store_true", help="Only dump; do not create the dashboard")
    args = ap.parse_args()

    dash = build(args.payload_table, args.spans_table)

    if args.dump:
        with open(args.dump, "w") as f:
            json.dump(dash, f, indent=2)
        print(f"Wrote template → {args.dump}")

    if args.no_create:
        return

    parent = args.parent_path
    if not parent:
        out, _, _ = cli(["current-user", "me", "--profile", args.profile])
        parent = "/Users/" + json.loads(out)["userName"]

    serialized = json.dumps(dash).replace("{{CATALOG}}", args.catalog).replace("{{SCHEMA}}", args.schema)
    payload = {"display_name": args.name, "warehouse_id": args.warehouse_id,
               "parent_path": parent, "serialized_dashboard": serialized}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        fn = f.name
    out, err, rc = cli(["api", "post", "/api/2.0/lakeview/dashboards", "--profile", args.profile, "--json", f"@{fn}"])
    os.unlink(fn)
    if rc != 0:
        print("CREATE FAILED:", err[:800]); sys.exit(1)
    d = json.loads(out)
    dash_id = d.get("dashboard_id")
    print(f"✅ Created dashboard '{args.name}'  id={dash_id}  at {parent}")

    if args.publish and dash_id:
        pub = {"warehouse_id": args.warehouse_id}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(pub, f)
            fn = f.name
        out, err, rc = cli(["api", "post", f"/api/2.0/lakeview/dashboards/{dash_id}/published", "--profile", args.profile, "--json", f"@{fn}"])
        os.unlink(fn)
        print("Published." if rc == 0 else f"Publish failed: {err[:400]}")


if __name__ == "__main__":
    main()
