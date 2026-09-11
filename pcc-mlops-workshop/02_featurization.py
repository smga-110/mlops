# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Featurization — Feature Tables & Automatic Feature Lookup
# MAGIC
# MAGIC **Team: Data Science / Model Training (Workspace A)**
# MAGIC
# MAGIC Notebook `01` produced a raw Delta table and a baseline model. Here we do the step that makes
# MAGIC the model **production-servable**: we promote the raw table into a **Unity Catalog Feature Table**
# MAGIC and re-package the model so it knows how to **look its own features up** at inference time.
# MAGIC
# MAGIC ### Feature Tables vs Feature Views — why Feature Tables
# MAGIC Databricks offers two abstractions in the Feature Engineering / Unity Catalog family:
# MAGIC
# MAGIC | | Feature **Tables** | Feature **Views** |
# MAGIC |---|---|---|
# MAGIC | Status | **GA** ✅ | Public Preview |
# MAGIC | What it is | A governed Delta table with a **primary key** | A declarative feature *definition* materialized on demand |
# MAGIC | Production use | Supported today | Not recommended until GA |
# MAGIC
# MAGIC PCC needs a **production** path, so this workshop uses **Feature Tables**.
# MAGIC
# MAGIC ### What "automatic feature lookup" buys you
# MAGIC Once a model is logged *with* its feature-lookup metadata, the caller only has to supply a
# MAGIC **key** (`patient_id`) — Databricks joins in the feature values automatically. This works in two
# MAGIC modes, and PCC cares about **both**:
# MAGIC
# MAGIC - **Offline / batch** (`score_batch`) — score a whole table of patient IDs. Demonstrated here.
# MAGIC - **Online / real-time** (serving endpoint) — sub-second scoring from a live app. Set up in `03`.

# COMMAND ----------

# MAGIC %pip install --quiet databricks-feature-engineering==0.13.0.1 "mlflow>=3.8.1" lightgbm==4.5.0 scikit-learn==1.5.2
# MAGIC %restart_python

# COMMAND ----------

# MAGIC %run ./00_init_setup

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1 — Split raw data into a Feature Table and a Labels table
# MAGIC A feature table holds **features keyed by an entity** — it must **not** contain the label
# MAGIC (the label isn't a property of the patient, it's the training target). So we split:
# MAGIC
# MAGIC - **Feature table** → `patient_id` (primary key) + all feature columns
# MAGIC - **Labels table** → `patient_id` + `readmitted_within_30_days`

# COMMAND ----------

raw = spark.table(bq(RAW_TABLE))

feature_cols = [c for c in raw.columns if c not in (PRIMARY_KEY, LABEL_COL)]
features_df = raw.select(PRIMARY_KEY, *feature_cols)
labels_df   = raw.select(PRIMARY_KEY, LABEL_COL)

labels_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(bq(LABELS_TABLE))
print(f"Feature columns ({len(feature_cols)}): {feature_cols}")
print(f"Labels table written to {LABELS_TABLE}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2 — Create the Unity Catalog Feature Table
# MAGIC `FeatureEngineeringClient.create_table` registers a Delta table with a declared **primary key**.
# MAGIC That primary key is what makes automatic lookup possible. The call is idempotent-friendly: we
# MAGIC drop-and-create so the workshop can be re-run cleanly.

# COMMAND ----------

from databricks.feature_engineering import FeatureEngineeringClient

fe = FeatureEngineeringClient()

# Clean re-run: remove any prior version of the feature table
spark.sql(f"DROP TABLE IF EXISTS {bq(FEATURE_TABLE)}")

fe.create_table(
    name=FEATURE_TABLE,
    primary_keys=[PRIMARY_KEY],
    df=features_df,
    description="PRTH patient features keyed by patient_id (30-day readmission model).",
)

# Enable Change Data Feed so the online store (notebook 03) can sync incrementally
# (required for TRIGGERED / CONTINUOUS publish modes).
spark.sql(f"ALTER TABLE {bq(FEATURE_TABLE)} SET TBLPROPERTIES (delta.enableChangeDataFeed = true)")
print(f"Created feature table {FEATURE_TABLE} (CDF enabled)")
display(spark.sql(f"SELECT * FROM {bq(FEATURE_TABLE)} LIMIT 5"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3 — Build a training set with a `FeatureLookup`
# MAGIC The training set = the **labels** (with their keys) + a declarative **lookup** into the feature
# MAGIC table. This is the object that teaches the model *which features come from where*, and it's
# MAGIC what makes the packaged model self-service at inference time.

# COMMAND ----------

from databricks.feature_engineering import FeatureLookup

feature_lookups = [
    FeatureLookup(
        table_name=FEATURE_TABLE,
        lookup_key=PRIMARY_KEY,
        # feature_names omitted -> look up ALL features in the table
    )
]

training_set = fe.create_training_set(
    df=spark.table(bq(LABELS_TABLE)),   # keys + label
    feature_lookups=feature_lookups,
    label=LABEL_COL,
    exclude_columns=[PRIMARY_KEY],  # key is for joining, not a model input
)

training_pdf = training_set.load_df().toPandas()
print(f"Training set shape: {training_pdf.shape}")
display(training_pdf.head())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4 — Train on the training set and log with `fe.log_model`
# MAGIC Same LightGBM pipeline as notebook `01`, but this time we log with **`fe.log_model`**, passing
# MAGIC the `training_set`. That embeds the feature-lookup metadata into the model, so downstream the
# MAGIC model can fetch features from just a key — offline **and** online.

# COMMAND ----------

import mlflow
import lightgbm as lgb
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

mlflow.set_registry_uri("databricks-uc")
# MLflow logs to this notebook's own experiment by default — no explicit path needed.

CATEGORICALS = ["primary_diagnosis", "discharge_disposition", "insurance_type"]
NUMERICS = [
    "age", "num_prior_admissions", "num_prior_ed_visits", "length_of_stay",
    "num_diagnoses", "num_medications", "comorbidity_score", "days_since_last_discharge",
]
FEATURES = NUMERICS + CATEGORICALS

X = training_pdf[FEATURES]
y = training_pdf[LABEL_COL]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

preprocessor = ColumnTransformer(
    transformers=[("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICALS)],
    remainder="passthrough",
)
model = Pipeline([
    ("prep", preprocessor),
    ("clf", lgb.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=31,
                               subsample=0.8, colsample_bytree=0.8, random_state=42)),
])

with mlflow.start_run(run_name="lgbm-feature-store") as run:
    model.fit(X_train, y_train)
    auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
    mlflow.log_metric("auc", auc)

    fe.log_model(
        model=model,
        artifact_path="model",
        flavor=mlflow.sklearn,
        training_set=training_set,          # <-- carries the feature-lookup metadata
        registered_model_name=MODEL_NAME,   # <-- new version of the SAME UC model
        # MLflow 3 defaults to the skops serializer, which rejects "untrusted" non-sklearn types
        # (LightGBM's Booster/LGBMClassifier). Use cloudpickle so the Pipeline saves cleanly.
        serialization_format="cloudpickle",
        # LightGBM lives inside the sklearn Pipeline, so MLflow's dependency inference misses it —
        # declare it explicitly. We let fe.log_model manage the feature-store client itself: on
        # MLflow 3.8.1+ / databricks-feature-engineering 0.13.0.1 it packages the Lakebase-aware
        # client so the serving container can resolve the online store.
        extra_pip_requirements=["lightgbm==4.5.0"],
    )
    fs_run_id = run.info.run_id

print(f"Feature-store model logged · run {fs_run_id} · AUC {auc:.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5 — Alias the servable version
# MAGIC We tag this feature-store-packaged version with the alias **`prod`**. The deployment team in
# MAGIC notebook `03` references the model by this alias — a stable pointer that survives re-training.

# COMMAND ----------

from mlflow.tracking import MlflowClient

client = MlflowClient()
versions = client.search_model_versions(f"name = '{MODEL_NAME}'")
latest = max(versions, key=lambda v: int(v.version))
client.set_registered_model_alias(MODEL_NAME, "prod", latest.version)
print(f"{MODEL_NAME} v{latest.version} -> alias 'prod'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6 — Offline automatic feature lookup (`score_batch`)
# MAGIC PCC's first use case: **batch scoring**. We pass a DataFrame of **just patient IDs** — no
# MAGIC features — and `fe.score_batch` joins the features in from the feature table automatically,
# MAGIC then returns predictions. This is the exact same packaged model that will serve online in `03`.

# COMMAND ----------

# A batch of patients to score — note we supply ONLY the key column
batch_to_score = spark.table(bq(LABELS_TABLE)).select(PRIMARY_KEY).limit(10)

scored = fe.score_batch(
    model_uri=f"models:/{MODEL_NAME}@prod",
    df=batch_to_score,
)
display(scored.select(PRIMARY_KEY, "prediction"))

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ **Feature Table created and a servable model packaged with automatic feature lookup.**
# MAGIC Offline batch scoring works. Next, the **deployment team in Workspace B** takes over in
# MAGIC **`03_deployment`** to publish the features online and stand up a real-time endpoint.
