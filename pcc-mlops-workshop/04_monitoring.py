# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · Inference Monitoring & Data Drift *(placeholder)*
# MAGIC
# MAGIC **Team: ML Engineering / Deployment (Workspace B)**
# MAGIC
# MAGIC Once the endpoint from `03` is live, Databricks can monitor it with almost no extra code. This
# MAGIC notebook is a **placeholder** we'll flesh out in a later session — the outline below shows where
# MAGIC we're headed.
# MAGIC
# MAGIC ### 1. Turn on inference logging on the endpoint
# MAGIC Enable an **inference table** so every request/response is durably logged to Unity Catalog. This
# MAGIC is a checkbox/config on the serving endpoint (AI Gateway `inference_table_config`) — no app code.
# MAGIC
# MAGIC ```
# MAGIC <catalog>.<schema>.<endpoint>_payload   # auto-populated request/response log (async, ~minutes)
# MAGIC ```
# MAGIC
# MAGIC ### 2. Lakehouse Monitoring on the inference table
# MAGIC Point **Databricks Lakehouse Monitoring** (`InferenceLog` profile) at the parsed payload table:
# MAGIC - `prediction_col` = the model's output probability
# MAGIC - `problem_type` = classification
# MAGIC - `granularity` = e.g. 1 hour / 1 day
# MAGIC
# MAGIC It auto-generates **profile** and **drift** metric tables and a **quality dashboard**.
# MAGIC
# MAGIC ### 3. Drift → retraining trigger
# MAGIC Wire a **Databricks Job** (retraining = notebook `01`) to fire when a drift metric breaches a
# MAGIC threshold, closing the MLOps loop: **train → deploy → monitor → retrain**.
# MAGIC
# MAGIC ### 4. AI/BI dashboard
# MAGIC A Lakeview dashboard over the payload + drift tables for the business view (volume, score
# MAGIC distribution, feature drift, risk bands).
# MAGIC
# MAGIC ---
# MAGIC > 🚧 **To be completed in a follow-up session.**

# COMMAND ----------

# MAGIC %md
# MAGIC *(No executable cells yet — see the outline above.)*
