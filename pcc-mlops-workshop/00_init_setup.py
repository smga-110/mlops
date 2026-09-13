# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Workshop Setup
# MAGIC
# MAGIC **PointClickCare · MLOps on Databricks Workshop**
# MAGIC
# MAGIC This notebook prepares a **per-user workspace** for the workshop so everyone can run the
# MAGIC hands-on notebooks side-by-side without colliding. It:
# MAGIC
# MAGIC 1. Reads the **signed-in user** (`current_user()`) and derives a safe, unique **schema name** from the email.
# MAGIC 2. Creates that schema inside a shared **catalog** (governed by Unity Catalog).
# MAGIC 3. Defines the **config variables** (catalog, schema, table names, model name, endpoint name) that every
# MAGIC    downstream notebook reuses via `%run ./00_init_setup`.
# MAGIC
# MAGIC > **Run this first.** Notebooks `01`–`04` start with `%run ./00_init_setup`, so they inherit the same names automatically.
# MAGIC
# MAGIC ---
# MAGIC ### Why derive the schema from the email?
# MAGIC In a shared workshop catalog, each attendee needs their own sandbox. Deriving it from
# MAGIC `current_user()` guarantees uniqueness with zero manual input. Note that Unity Catalog
# MAGIC identifiers may **not** contain `.` (the namespace separator) or `@`, so we sanitize the
# MAGIC email — `jane.doe@pointclickcare.com` becomes the schema `jane_doe`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters
# MAGIC The only thing an attendee may need to change is the **catalog** — it must be a catalog you
# MAGIC have `CREATE SCHEMA` on. Everything else is derived automatically.

# COMMAND ----------

dbutils.widgets.text("catalog", "pcc_mlops_demo_catalog", "Catalog (must have CREATE SCHEMA)")
dbutils.widgets.text("schema_override", "", "Schema override (blank = derive from email)")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA_OVERRIDE = dbutils.widgets.get("schema_override").strip()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Derive a safe schema name from the signed-in user

# COMMAND ----------

import re


def sanitize_identifier(raw: str) -> str:
    """Turn an arbitrary string (e.g. an email local-part) into a legal, lowercase
    Unity Catalog identifier: keep [a-z0-9_], collapse everything else to '_'."""
    ident = raw.strip().lower()
    ident = re.sub(r"[^a-z0-9_]", "_", ident)   # '.', '@', '-', etc. -> '_'
    ident = re.sub(r"_+", "_", ident).strip("_")  # collapse/trim underscores
    if not ident:
        ident = "workshop_user"
    if ident[0].isdigit():                       # identifiers can't start with a digit
        ident = f"u_{ident}"
    return ident


# current_user() returns the full email of the signed-in principal
current_user = spark.sql("SELECT current_user()").collect()[0][0]
email_local_part = current_user.split("@")[0]

if SCHEMA_OVERRIDE:
    SCHEMA = sanitize_identifier(SCHEMA_OVERRIDE)
else:
    SCHEMA = sanitize_identifier(email_local_part)

print(f"Signed-in user : {current_user}")
print(f"Derived schema : {SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create the schema
# MAGIC `CREATE SCHEMA IF NOT EXISTS` is idempotent — safe to re-run.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`")
spark.sql(f"USE CATALOG `{CATALOG}`")
spark.sql(f"USE SCHEMA `{SCHEMA}`")
print(f"Using {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Shared config
# MAGIC These names are used consistently across notebooks `01`–`04`. Because this notebook is
# MAGIC `%run` from the others, these Python variables become available there automatically.

# COMMAND ----------

# Fully-qualified object names used across the workshop
RAW_TABLE       = f"{CATALOG}.{SCHEMA}.prth_raw_features"        # NB01: raw modeling dataset (Delta)
FEATURE_TABLE   = f"{CATALOG}.{SCHEMA}.prth_patient_features"    # NB02: UC Feature Table (has a primary key)
LABELS_TABLE    = f"{CATALOG}.{SCHEMA}.prth_labels"             # NB02: keys + label, for building the training set
MODEL_NAME      = f"{CATALOG}.{SCHEMA}.prth_readmission_lgbm"    # UC-registered model (both baseline & fe-packaged)
ENDPOINT_NAME   = f"prth-readmission-{SCHEMA}".replace("_", "-")  # serving endpoints use '-' not '_'

# Primary key for the feature table / automatic feature lookup
PRIMARY_KEY = "patient_id"
LABEL_COL   = "readmitted_within_30_days"


def bq(fqn: str) -> str:
    """Backtick-quote each part of a dotted UC name for use in Spark / SQL.

    Unity Catalog allows special characters (e.g. hyphens, common in the workspace-default
    catalog like `catalog-dbw-...`) in names, but Spark SQL then requires them back-quoted or
    it raises INVALID_IDENTIFIER. Use bq() for Spark table ops (saveAsTable, spark.table,
    spark.sql). Do NOT use it for the Feature Engineering client, MLflow registered_model_name,
    or `models:/` URIs — those take the raw three-part name and back-ticks would break them.
    """
    return ".".join(f"`{part}`" for part in fqn.split("."))

print("Config for this workshop run:")
for k, v in {
    "CATALOG": CATALOG,
    "SCHEMA": SCHEMA,
    "RAW_TABLE": RAW_TABLE,
    "FEATURE_TABLE": FEATURE_TABLE,
    "LABELS_TABLE": LABELS_TABLE,
    "MODEL_NAME": MODEL_NAME,
    "ENDPOINT_NAME": ENDPOINT_NAME,
    "PRIMARY_KEY": PRIMARY_KEY,
    "LABEL_COL": LABEL_COL,
}.items():
    print(f"  {k:16} = {v}")

# COMMAND ----------

# MAGIC %md
# MAGIC ✅ **Setup complete.** Proceed to **`01_model_training`**.