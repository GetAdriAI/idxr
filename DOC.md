## SAP KB Indexing Lifecycle

Picture the journey of “ECC Ops Helper,” an SAP support chatbot that evolves alongside your organization.

All CLI commands now require an explicit model registry reference so the tooling knows which Pydantic models to load. For the built-in ECC registry, set:

```bash
export MODEL_REGISTRY_TARGET="kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY"
```

Swap in your own registry when extending the stack, then pass `--model "$MODEL_REGISTRY_TARGET"` to every `prepare_datasets.py` and `vectorize.py` invocation shown below.

### 1. Launch the Initial Collection

In week one, you load the baseline ECC exports so the assistant can answer core questions.

```bash
# Scaffold an all-model config stub
prepare_datasets.py new-config ecc-foundation --model "$MODEL_REGISTRY_TARGET"

# Fill in CSV locations, then preprocess
prepare_datasets.py \
  --model "$MODEL_REGISTRY_TARGET" \
  --config configs/ecc_foundation.json \
  --output-root build/partitions

# Index the first partition into a fresh collection
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std
```

This emits `partition_00000`, stores a manifest, and seeds the Chroma collection.

When sanitising rows, `prepare_datasets.py` now tries to repair newline-fractured records by stitching consecutive physical lines together around any configured `malformed_column`. Rows that still fall short of the expected column count after reconstruction are skipped with a warning that includes the affected row span, so malformed data never slips through silently.

### 2. Append New Rows

A month later Treasury drops a hotfix CSV for existing tables.

```bash
# Generate a migration-like stub for the affected model(s)
prepare_datasets.py new-config treasury-hotfix --models Table --model "$MODEL_REGISTRY_TARGET"

# Point the stub at the new CSV and preprocess with the same manifest
prepare_datasets.py \
  --model "$MODEL_REGISTRY_TARGET" \
  --config configs/treasury_hotfix.json \
  --output-root build/partitions \
  --manifest build/partitions/manifest.json

# Index only the new rows (resume metadata avoids duplicates)
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --resume
```

Row digests keep the old partitions untouched while the new ones stack on top.

### 3. Add New Models

Two weeks later the Basis team wants Function Modules searchable.

```bash
prepare_datasets.py new-config basis-drop --models Function --model "$MODEL_REGISTRY_TARGET"
```

After adding the CSV path, run preprocess and index as before. The manifest adds a partition dedicated to the new model and the embeddings merge seamlessly into `ecc-std`.

### 4. Update After Schema Changes

SAP ships a DDIC patch that changes `Table` and `Field`. Update the Pydantic models and rerun preprocessing:

```bash
prepare_datasets.py \
  --model "$MODEL_REGISTRY_TARGET" \
  --config configs/ddic_refresh.json \
  --output-root build/partitions \
  --manifest build/partitions/manifest.json
```

The tool hashes schemas, marks prior partitions as `stale`, copies unaffected models into new directories, and streams the updated rows—partition metadata now records replacements.

To reindex and optionally clean up the stale data:

```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --resume \
  --delete-stale
```

Each indexed document gets a `partition_name` tag so stale partitions can be safely deleted from Chroma once replacements are in place.

---

### Operational Checklist

- Inspect `build/partitions/manifest.json` after every run to see schema signatures, replacement relationships, and stale flags.
- Validate the collection with:
  ```bash
  vectorize.py display --model "$MODEL_REGISTRY_TARGET" --collection ecc-std --persist-dir build/vector
  ```
- Omit `--delete-stale` until you’re ready to retire old embeddings; rerun the indexing command with the flag when you want to purge them.

With this lifecycle, “ECC Ops Helper” keeps pace as your data estate grows, new model coverage lands smoothly, and schema churn becomes a planned migration instead of a crisis.

### 5. Retire or Purge Data with Drop Configs

Sometimes the business demands that a model’s vectors disappear—regulatory purges, corrupted ingests, or entire product sunsets. The **model-centric drop flow** mirrors the rest of the lifecycle so clean-up is deliberate, auditable, and reviewable.

#### a. Plan the Drop

Ask the manifest which partitions currently hold the models you want to remove.

```bash
# Generate a drop plan for Table + Field before July 2024
prepare_datasets.py plan-drop \
  --manifest build/partitions/manifest.json \
  --model "$MODEL_REGISTRY_TARGET" \
  --models Table,Field \
  --before 2024-07-01 \
  --reason "GDPR purge: EU data pre-July" \
  --output configs/drop/gdpr_2024-07.json
```

The command inspects `manifest.json`, finds matching partitions, records schema versions, and writes a drop config you can review via PR before anything is deleted.

```json
{
  "generated_at": "2024-07-02T10:15:42",
  "source_manifest": ".../manifest.json",
  "before": "2024-07-01",
  "models": {
    "Table": {
      "partitions": ["partition_00037", "partition_00038"],
      "schema_versions": [2, 3],
      "reason": "GDPR purge: EU data pre-July"
    },
    "Field": {
      "partitions": ["partition_00038"],
      "reason": "GDPR purge: EU data pre-July"
    }
  }
}
```

#### b. Apply to the Manifest (Dry Run First)

```bash
# Inspect impact
prepare_datasets.py apply-drop \
  --config configs/drop/gdpr_2024-07.json \
  --manifest build/partitions/manifest.json \
  --model "$MODEL_REGISTRY_TARGET"

# Execute and optionally remove local CSVs
prepare_datasets.py apply-drop \
  --config configs/drop/gdpr_2024-07.json \
  --manifest build/partitions/manifest.json \
  --model "$MODEL_REGISTRY_TARGET" \
  --apply --local --performed-by ops-bot
```

The manifest now records `deleted=true`, `deleted_at`, and the drop reason for the targeted model/partition pairs, plus an audit log entry under `drops`.

#### c. Purge from Chroma

Use the same config to delete embeddings.

```bash
# Dry run (prints the metadata filters only)
vectorize.py apply-drop \
  --model "$MODEL_REGISTRY_TARGET" \
  --config configs/drop/gdpr_2024-07.json \
  --collection ecc-std

# Execute against the production collection and update the manifest
vectorize.py apply-drop \
  --model "$MODEL_REGISTRY_TARGET" \
  --config configs/drop/gdpr_2024-07.json \
  --collection ecc-std \
  --partition-manifest build/partitions/manifest.json \
  --apply --performed-by ops-bot
```

Under the hood the CLI turns each model block into metadata filters such as:

```python
{"$and": [
    {"model_name": "Table"},
    {"partition_name": {"$in": ["partition_00037", "partition_00038"]}},
    {"schema_version": {"$in": [2, 3]}}
]}
```

That means you can target an entire model, specific partitions, or only certain schema versions. `partition_name`, `model_name`, and `schema_version` already live in each document’s metadata, so the delete is precise.

#### d. Recovery Story

- Drop configs live alongside ingest configs, so reverting is as easy as rolling back the file in Git and re-running `prepare_datasets.py apply-drop --apply` to clear the deleted flags, then re-indexing.
- If you only marked entries deleted (no local removal), re-running `vectorize.py index --resume` will rebuild the vectors.

#### Common Use Cases

- **Regulatory purge:** Law requires forgetting data for a specific business unit or time range.
- **Security response:** A CSV accidentally contained PII—drop the affected models immediately.
- **Rollback:** A new export introduced bad rows; drop those partitions, regenerate the ingest config, rerun indexing.
- **Product sunset:** Retire an entire knowledge domain when a service is decommissioned.

The drop flow completes the lifecycle: every addition, migration, and deletion now runs through the same config-driven, reviewable pipeline.
