# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Model Training — Predicting Return to Hospital (PRTH)
# MAGIC
# MAGIC **Team: Data Science / Model Training (Workspace A)**
# MAGIC
# MAGIC This notebook trains a **LightGBM** classifier that predicts whether a patient will be
# MAGIC **readmitted within 30 days** of discharge. The point here is **not** the model itself —
# MAGIC that's owned by a separate team — but to show the **MLOps best practices** Databricks gives
# MAGIC you for free during training:
# MAGIC
# MAGIC - **MLflow experiment tracking** — parameters, metrics, and artifacts captured on every run.
# MAGIC - **Model signature & input example** — so the schema is enforced at serving time.
# MAGIC - **Unity Catalog Model Registry** — the trained model becomes a **governed UC object**
# MAGIC   (`catalog.schema.model`) with versions, lineage, and cross-workspace access control.
# MAGIC - A **raw features Delta table** — the governed dataset that the next notebook promotes into a
# MAGIC   **Feature Table**.
# MAGIC
# MAGIC > **Handoff preview:** once this model is registered in Unity Catalog, a *different team in a
# MAGIC > different workspace* can deploy it — with nothing more than the right UC privileges. We prove
# MAGIC > that in notebook `03`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Install dependencies
# MAGIC `lightgbm` is not in the base runtime. We also pin `mlflow` and the
# MAGIC `databricks-feature-engineering` SDK (used in notebook `02`) so the versions match across the workshop.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-feature-engineering==0.13.0.1 "mlflow>=3.8.1" lightgbm==4.5.0 scikit-learn==1.5.2
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load shared config
# MAGIC `%run` executes the setup notebook and imports its variables (`CATALOG`, `SCHEMA`, `RAW_TABLE`, `MODEL_NAME`, …).

# COMMAND ----------

# MAGIC %run ./00_init_setup

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Generate a synthetic PRTH dataset
# MAGIC In a real deployment these rows would come from your EHR / claims history. For the workshop we
# MAGIC synthesize a clinically-plausible cohort so the notebook is self-contained and reproducible.
# MAGIC Readmission risk is driven by prior utilization, comorbidity burden, length of stay, and
# MAGIC discharge disposition — the usual suspects in a 30-day readmission model.

# COMMAND ----------

import numpy as np
import pandas as pd

rng = np.random.default_rng(42)
N = 4000

# --- Categorical vocabularies -------------------------------------------------
primary_dx = np.array(["heart_failure", "copd", "pneumonia", "sepsis", "diabetes", "afib", "renal"])
discharge_disp = np.array(["home", "home_health", "snf", "rehab", "ama"])  # ama = against medical advice
insurance = np.array(["medicare", "medicaid", "commercial", "self_pay"])

# --- Draw features ------------------------------------------------------------
age                 = np.clip(rng.normal(72, 14, N), 18, 100).round().astype(int)
num_prior_admissions = rng.poisson(1.2, N)
num_prior_ed_visits  = rng.poisson(0.9, N)
length_of_stay       = np.clip(rng.gamma(2.0, 2.2, N), 1, 40).round().astype(int)
num_diagnoses        = np.clip(rng.poisson(6, N), 1, 25)
num_medications      = np.clip(rng.poisson(9, N), 0, 35)
comorbidity_score    = np.clip(rng.normal(3.5, 2.0, N), 0, 15).round(1)   # Charlson-style index
days_since_last_discharge = np.clip(rng.exponential(120, N), 0, 900).round().astype(int)
primary_diagnosis    = rng.choice(primary_dx, N, p=[.18, .16, .14, .12, .18, .12, .10])
discharge_disposition = rng.choice(discharge_disp, N, p=[.45, .22, .18, .12, .03])
insurance_type       = rng.choice(insurance, N, p=[.55, .18, .22, .05])

# --- Build a latent risk score, then sample the label from it -----------------
disp_risk = pd.Series(discharge_disposition).map(
    {"home": -0.4, "home_health": 0.1, "snf": 0.5, "rehab": 0.2, "ama": 1.1}
).to_numpy()
dx_risk = pd.Series(primary_diagnosis).map(
    {"heart_failure": 0.8, "copd": 0.6, "pneumonia": 0.3, "sepsis": 0.7,
     "diabetes": 0.2, "afib": 0.3, "renal": 0.6}
).to_numpy()

logit = (
    -3.1
    + 0.020 * (age - 70)
    + 0.45 * num_prior_admissions
    + 0.30 * num_prior_ed_visits
    + 0.06 * length_of_stay
    + 0.05 * num_diagnoses
    + 0.03 * num_medications
    + 0.12 * comorbidity_score
    - 0.0015 * days_since_last_discharge
    + disp_risk
    + dx_risk
    + rng.normal(0, 0.5, N)          # irreducible noise
)
prob = 1 / (1 + np.exp(-logit))
readmitted = (rng.uniform(0, 1, N) < prob).astype(int)

pdf = pd.DataFrame({
    "patient_id": np.arange(100000, 100000 + N),
    "age": age,
    "num_prior_admissions": num_prior_admissions,
    "num_prior_ed_visits": num_prior_ed_visits,
    "length_of_stay": length_of_stay,
    "num_diagnoses": num_diagnoses,
    "num_medications": num_medications,
    "comorbidity_score": comorbidity_score,
    "days_since_last_discharge": days_since_last_discharge,
    "primary_diagnosis": primary_diagnosis,
    "discharge_disposition": discharge_disposition,
    "insurance_type": insurance_type,
    "readmitted_within_30_days": readmitted,
})

print(f"Generated {len(pdf):,} patients · readmission rate = {pdf['readmitted_within_30_days'].mean():.1%}")
display(pdf.head(10))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Persist the raw features as a governed Delta table
# MAGIC This is the single source of truth the featurization notebook builds on. Writing it to Unity
# MAGIC Catalog immediately gives you ACID storage, lineage, and access control.

# COMMAND ----------

spark.createDataFrame(pdf).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(bq(RAW_TABLE))
print(f"Wrote raw features to {RAW_TABLE}")
display(spark.sql(f"SELECT * FROM {bq(RAW_TABLE)} LIMIT 5"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Train LightGBM with MLflow tracking
# MAGIC We point the MLflow **Model Registry** at Unity Catalog (`databricks-uc`) so the registered
# MAGIC model is a governed UC object. We build a scikit-learn `Pipeline` (one-hot for categoricals +
# MAGIC LightGBM) so the model is fully self-contained — categorical encoding travels with the model.

# COMMAND ----------

import mlflow
import lightgbm as lgb
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score, f1_score
from mlflow.models.signature import infer_signature

mlflow.set_registry_uri("databricks-uc")            # register models INTO Unity Catalog
# Log to an explicit experiment under the user's home folder. This is stable and always exists,
# unlike the notebook's default experiment (which can end up pointing at a deleted experiment if
# the notebook is re-cloned or a related schema is dropped).
mlflow.set_experiment(f"/Users/{current_user}/prth-readmission")

CATEGORICALS = ["primary_diagnosis", "discharge_disposition", "insurance_type"]
NUMERICS = [
    "age", "num_prior_admissions", "num_prior_ed_visits", "length_of_stay",
    "num_diagnoses", "num_medications", "comorbidity_score", "days_since_last_discharge",
]
FEATURES = NUMERICS + CATEGORICALS

X = pdf[FEATURES]
y = pdf[LABEL_COL]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# COMMAND ----------

params = {
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "max_depth": -1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
}

preprocessor = ColumnTransformer(
    transformers=[("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICALS)],
    remainder="passthrough",
)
model = Pipeline([
    ("prep", preprocessor),
    ("clf", lgb.LGBMClassifier(**params)),
])

with mlflow.start_run(run_name="lgbm-baseline") as run:
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]
    preds = (proba >= 0.5).astype(int)
    metrics = {
        "auc": roc_auc_score(y_test, proba),
        "accuracy": accuracy_score(y_test, preds),
        "precision": precision_score(y_test, preds),
        "recall": recall_score(y_test, preds),
        "f1": f1_score(y_test, preds),
    }

    # --- Log the things a governed training run should always capture ---------
    mlflow.log_params(params)
    mlflow.log_param("n_features", len(FEATURES))
    mlflow.log_param("train_rows", len(X_train))
    mlflow.log_metrics(metrics)

    signature = infer_signature(X_test, proba)
    mlflow.sklearn.log_model(
        sk_model=model,
        artifact_path="model",
        signature=signature,
        input_example=X_test.head(3),
        registered_model_name=MODEL_NAME,     # <-- registers into Unity Catalog
        # MLflow 3 defaults to the skops serializer, which rejects "untrusted" non-sklearn types
        # (LightGBM's Booster/LGBMClassifier). Use cloudpickle so the Pipeline saves cleanly.
        serialization_format="cloudpickle",
    )

    run_id = run.info.run_id
    print(f"Run {run_id}")
    for k, v in metrics.items():
        print(f"  {k:10} = {v:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Inspect feature importance (logged as an artifact)
# MAGIC A quick sanity check that the model learned the drivers we'd expect (prior utilization,
# MAGIC comorbidity, length of stay). The plot is attached to the MLflow run.

# COMMAND ----------

import matplotlib.pyplot as plt

ohe_names = model.named_steps["prep"].named_transformers_["cat"].get_feature_names_out(CATEGORICALS)
feat_names = list(ohe_names) + NUMERICS
importances = model.named_steps["clf"].feature_importances_
imp = pd.Series(importances, index=feat_names).sort_values(ascending=True).tail(15)

fig, ax = plt.subplots(figsize=(8, 6))
imp.plot.barh(ax=ax)
ax.set_title("Top 15 feature importances — PRTH LightGBM")
ax.set_xlabel("gain")
plt.tight_layout()

with mlflow.start_run(run_id=run_id):
    mlflow.log_figure(fig, "feature_importance.png")
plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 — Confirm the model is registered in Unity Catalog
# MAGIC The model now lives at `MODEL_NAME` as a versioned, governed UC object. We tag this version
# MAGIC as the workshop baseline. (In notebook `02` we re-log a **feature-store-packaged** version that
# MAGIC knows how to look features up automatically.)

# COMMAND ----------

from mlflow.tracking import MlflowClient

client = MlflowClient()
versions = client.search_model_versions(f"name = '{MODEL_NAME}'")
latest = max(versions, key=lambda v: int(v.version))
client.set_registered_model_alias(MODEL_NAME, "baseline", latest.version)

print(f"Registered UC model : {MODEL_NAME}")
print(f"Latest version      : v{latest.version}  (alias: baseline)")
print(f"Test AUC            : {metrics['auc']:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ **Model trained & registered in Unity Catalog.** Proceed to **`02_featurization`** to promote the
# MAGIC raw table into a **Feature Table** and package the model for **automatic feature lookup**.
