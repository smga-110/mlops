# MLOps on Databricks — E2E vWorkshop

An end-to-end walkthrough of the ML lifecycle on Databricks, built around a **Predicting Return
to Hospital (PRTH)** model: train a LightGBM classifier that predicts 30-day readmission, register
it in Unity Catalog, serve it — offline and in real time — with **automatic feature lookup**, and
(later) monitor it

The notebooks are designed to be run **in order**, and to mirror a real org where the **training
team** and the **deployment team** work in **separate workspaces attached to the same Unity Catalog
metastore**.

## Notebooks

| Notebook | Team / Workspace | What it does |
|---|---|---|
| `00_init_setup` | A (training) | Derives a per-user schema from your email and creates it; defines shared config. Run first (the others `%run` it). |
| `01_model_training` | A (training) | Generates synthetic PRTH data, trains **LightGBM**, logs metrics/params/signature to **MLflow**, registers the model to **Unity Catalog**, and writes the raw features Delta table. |
| `02_featurization` | A (training) | Promotes the raw table to a **UC Feature Table**, packages the model with `fe.log_model` for **automatic feature lookup**, and demonstrates **offline batch scoring** (`score_batch`). |
| `03_deployment` | **B (deployment)** | Cross-workspace handoff (UC grants), publishes the feature table to a **Lakebase online store**, and deploys a **real-time serving endpoint** that scores from just a patient key. |
| `04_monitoring` | B (deployment) | Placeholder — inference logging + drift monitoring outline (to be completed later). |

## Prerequisites

- **Serverless** notebook compute (recommended), or a cluster on **Databricks Runtime 14.2 for ML or above**.
- A Unity Catalog **catalog** where you have `CREATE SCHEMA` (and privileges to create feature
  tables, online stores, and serving endpoints).
- The notebooks pin **`databricks-feature-engineering==0.13.0.1`** and **`mlflow>=3.8.1`** — these
  are required for the Lakebase online feature store + serving path (they install automatically).

## How to run

### 1. Set the widgets
The only thing you normally change is the **`catalog`** widget.

- **`00`, `01`, `02`** use two widgets (created when the notebook runs `%run ./00_init_setup`):
  - **`catalog`** — set to a catalog you have `CREATE SCHEMA` on (default `pcc_mlops_workshop` is a placeholder).
  - **`schema_override`** — leave **blank** to auto-create a personal schema from your email
    (`jane.doe@…` → `jane_doe`), or set it explicitly.
- **`03_deployment`** uses **`catalog`** and **`schema`** — set both to match what `00`–`02` used
  (e.g. `catalog=<your catalog>`, `schema=<your derived schema>`).

> Tip: run the first cell (or the `%run ./00_init_setup` cell) once so the widgets appear at the top,
> set them, then run the notebook top to bottom.

### 2. Run in order
`01_model_training` → `02_featurization` → `03_deployment`.

- In the cross-workspace scenario, run `01`–`02` in the **training** workspace and `03` in the
  **deployment** workspace (same metastore). The grants in `03` Step 1 are what make the handoff work.
- To run everything in a single workspace, just use the same catalog/schema throughout.

### 3. Expect the endpoint build to take time
`03` Step 3 (the real-time endpoint) builds a serving container and wires up the online feature
lookup — **~20–30 minutes on first deploy**. The notebook waits for it, then Step 4 scores a few
patients from just `patient_id`.

## Notes & gotchas

- **Clean slate matters.** These notebooks create feature tables, an online store, and a serving
  endpoint. If you re-run `02` (which drops & recreates the feature table), the online-table link
  from a prior run goes stale and the endpoint fails with *"No suitable online store found."* If that
  happens, **uncomment the reset block** in `03` Step 2 (it deletes the old online store + synced
  table so the publish re-links cleanly), then re-run.
- **MLflow 3 + LightGBM:** `log_model` uses `serialization_format="cloudpickle"` because MLflow 3's
  default (skops) rejects LightGBM's types. This is already set in the notebooks.
- **Offline vs online lookup:** `02` shows offline `score_batch` (batch inference from the Delta
  feature table); `03` shows real-time serving with online lookup from Lakebase. Same registered
  model, two serving modes.
