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

Need more throughput? Add `--parallel-partitions <workers>` to fan out multiple partitions at a time.
The CLI caps concurrency at the number you supply and automatically falls back to sequential mode when features like `--e2e-test-run` require deterministic sampling.

Row digests keep the old partitions untouched while the new ones stack on top.
Each partition also writes `<model>.digests` sidecars so later runs can reload dedupe hashes without re-scanning the CSVs.
When targeting Chroma Cloud, the indexer now creates one collection per partition (optionally prefixed via `--collection`); local persistent runs continue to use the single collection name you supply.
Using `--delete-stale` in this mode drops the whole per-partition collection before replacements are indexed, mirroring the previous single-collection cleanup semantics.
Need a lightweight smoke test? Add `--e2e-test-run` to any indexing command to sample random rows from every CSV, index just those records, and produce an audit JSON of what was ingested.
The sampling mode works with both local persistent stores (supply `--persist-dir`) and Chroma Cloud HTTP runs, giving you a consistent validation path before committing to a full index.
Remember that `prepare_datasets.py` only normalises CSV structure; the actual Pydantic validation happens when `vectorize.py` streams rows through `iter_documents()`, so schema errors surface during indexing rather than preprocessing.
Running against Chroma Cloud? Use `--client-type cloud --chroma-api-token ...` (optionally `--chroma-cloud-tenant`/`--chroma-cloud-database`) or stick with the lower-level `--client-type http` flags when you want to specify headers manually.

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

---

### Document Semantic Content and Metadata

Every document indexed in the vector store contains metadata that describes its content structure. Understanding what gets indexed and how it's marked is crucial for querying and filtering.

#### What Gets Indexed

The `build_semantic_text()` function determines the actual text content that gets embedded. The behavior depends on the model's semantic fields:

**1. When semantic fields have values:**

The text to be indexed consists of all non-empty semantic field values joined with newlines.

```python
# Example: ProductModel with semantic_fields=("title", "description")
{
    "product_id": "P123",
    "title": "Laptop Computer",
    "description": "High-performance laptop for professionals",
    "category": "Electronics",
    "price": 1299.99
}

# Indexed text:
"""
Laptop Computer
High-performance laptop for professionals
"""
```

**2. When semantic field values are None or empty:**

The entire model is serialized as JSON and that becomes the indexed text.

```python
# Example: PersonWithSemantics with description=None
{
    "name": "John Doe",
    "description": None,  # semantic field is None
    "age": 30,
    "email": "john@example.com"
}

# Indexed text:
"""
{"age": 30, "description": null, "email": "john@example.com", "name": "John Doe"}
"""
```

**3. When there are no semantic fields defined:**

The entire model is serialized as JSON and that becomes the indexed text.

```python
# Example: PersonNoSemantics with semantic_fields=()
{
    "name": "Bob Smith",
    "age": 40,
    "email": "bob@example.com"
}

# Indexed text:
"""
{"age": 40, "email": "bob@example.com", "name": "Bob Smith"}
"""
```

#### The `has_sem` Metadata Field

Every document's metadata includes a `has_sem` field (short for "has semantic value") that indicates whether the document contains meaningful semantic content:

- **`has_sem: True`** - The document has one or more non-empty semantic fields with meaningful content (not just whitespace)
- **`has_sem: False`** - The document either:
  - Has no semantic fields defined in the model
  - Has semantic fields that are all None, empty, or whitespace-only
  - Falls back to JSON serialization

#### Empty Value Filtering

The indexer filters out the following values from semantic fields:
- `None`
- Empty strings `""`
- Empty lists `[]`
- Empty dicts `{}`
- Strings containing only whitespace (marked as `has_sem: False`)

#### Querying by Semantic Content

Use the `has_sem` metadata field to filter your queries:

```python
# Find only documents with genuine semantic content
collection.query(
    query_texts=["SAP table structures"],
    where={"has_sem": True},
    n_results=10
)

# Find documents that use JSON fallback (no semantic fields)
collection.query(
    query_texts=["configuration data"],
    where={"has_sem": False},
    n_results=10
)
```

This distinction helps separate documents with rich textual descriptions from those that are purely structured data, allowing you to tune retrieval strategies based on content type.

---

### Logging Configuration for Large-Scale Indexing

When indexing millions of records, log output can grow significantly. The indexer supports file logging with automatic rotation to prevent disk space issues and manage log files efficiently.

#### Enabling File Logging with Rotation

Use the following CLI arguments to enable file logging:

```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file logs/vectorize.log \
  --log-max-bytes 104857600 \
  --log-backup-count 10
```

#### Logging Arguments

- **`--log-file <path>`**: Path to the log file. If not specified, logs only go to console. The directory is created automatically if it doesn't exist.

- **`--log-level <level>`**: Logging verbosity level. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Default: `INFO`.

- **`--log-max-bytes <bytes>`**: Maximum size of a single log file before rotation in bytes. Default: `104857600` (100 MB). When the log file reaches this size, it's rotated automatically.

- **`--log-backup-count <count>`**: Number of rotated log files to keep. Default: `10`. With default settings (100 MB per file, 10 backups), you'll use about 1 GB of disk space for logs.

- **`--log-no-console`**: Disable console output (only log to file). Useful for background processes or when you only want file logs.

#### Log Rotation Behavior

When a log file reaches `--log-max-bytes`:
1. The current log file is renamed with a `.1` suffix (e.g., `vectorize.log` → `vectorize.log.1`)
2. Previous backup files are incremented (`.1` → `.2`, `.2` → `.3`, etc.)
3. The oldest backup (`.10` with default settings) is deleted
4. A new `vectorize.log` file is created

This ensures your disk space usage is bounded while preserving recent logs for debugging.

#### Common Logging Configurations

**1. Development (verbose logging to console):**
```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --config data/config.json \
  --collection ecc-std \
  --persist-dir ./chroma \
  --log-level DEBUG
```
Use this during development to see detailed logs in your terminal without creating files.

**2. Default file logging (recommended for most users):**
```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file logs/vectorize.log
```
This uses sensible defaults: 100 MB files, 10 backups (1 GB total). Logs appear both in console and file.

**3. Production (file logging only, larger files):**
```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file /var/log/vectorize/indexing.log \
  --log-max-bytes 524288000 \
  --log-backup-count 20 \
  --log-no-console
```
This configuration uses 500 MB files with 20 backups (10 GB total), with no console output for clean background execution.

**4. Background processing with timestamped logs:**
```bash
nohup vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file logs/vectorize_$(date +%Y%m%d_%H%M%S).log \
  --log-no-console \
  > /dev/null 2>&1 &
```
Creates a new log file with timestamp for each run, useful for keeping separate logs per indexing session.

**5. Parallel partitions with file logging:**
```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --parallel-partitions 4 \
  --log-file logs/parallel_index.log \
  --log-max-bytes 209715200 \
  --log-backup-count 15
```
When processing partitions in parallel, larger log files (200 MB) with more backups (15) handle the increased log volume.

**6. Chroma Cloud with file logging:**
```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --client-type cloud \
  --chroma-api-token "$CHROMA_TOKEN" \
  --collection ecc-std \
  --log-file logs/cloud_index.log \
  --log-level INFO
```
Logs network operations and API calls to file while indexing to Chroma Cloud.

**7. Resume mode with existing logs:**
```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --resume \
  --log-file logs/vectorize.log \
  --log-level INFO
```
When resuming, logs append to existing file until it rotates. Rotation preserves previous run's logs in backup files.

#### Programmatic Usage

You can also configure logging programmatically:

```python
from indexer.vectorize_lib import setup_logging
from pathlib import Path

# Enable file logging with rotation
setup_logging(
    log_level="INFO",
    log_file=Path("logs/vectorize.log"),
    max_bytes=100 * 1024 * 1024,  # 100 MB
    backup_count=10,
    console_output=True,
)
```

#### Log File Location Best Practices

- **Development**: Use relative paths like `logs/vectorize.log` in your project directory
- **Production**: Use absolute paths in a dedicated log directory like `/var/log/vectorize/`
- **Date-stamped logs**: Include timestamps in filenames for long-running processes: `logs/vectorize_$(date +%Y%m%d_%H%M%S).log`
- **Ensure write permissions**: The process must have write access to the log directory

#### Monitoring Disk Usage

With default settings (100 MB × 10 backups), expect ~1 GB of log storage. Monitor your log directory:

```bash
# Check total log size
du -sh logs/

# List log files by size
ls -lh logs/vectorize.log*

# Watch logs in real-time
tail -f logs/vectorize.log
```

#### Real-World Scenarios

**Scenario 1: Indexing 16 Million Records**

For very large datasets, use aggressive rotation to prevent any single file from becoming unwieldy:

```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file /var/log/vectorize/large_index.log \
  --log-max-bytes 52428800 \
  --log-backup-count 50 \
  --log-level INFO \
  --log-no-console
```
This uses 50 MB files with 50 backups (2.5 GB total). Smaller files are easier to transfer, archive, or analyze.

**Scenario 2: Debugging Failed Indexing Runs**

When troubleshooting issues, capture everything with DEBUG level:

```bash
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file logs/debug_$(date +%Y%m%d_%H%M%S).log \
  --log-level DEBUG \
  --log-max-bytes 104857600 \
  --log-backup-count 5
```
Debug logs are verbose, so keep fewer backups and use timestamps to separate runs.

**Scenario 3: CI/CD Pipeline Integration**

For automated pipelines, capture logs per build:

```bash
#!/bin/bash
BUILD_ID="${CI_BUILD_ID:-$(date +%Y%m%d_%H%M%S)}"
LOG_DIR="logs/builds/$BUILD_ID"
mkdir -p "$LOG_DIR"

vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection "ecc-std-$BUILD_ID" \
  --log-file "$LOG_DIR/vectorize.log" \
  --log-max-bytes 104857600 \
  --log-backup-count 3 \
  --log-no-console

# Archive logs on completion
tar -czf "logs/archives/build_${BUILD_ID}_logs.tar.gz" "$LOG_DIR"
```

**Scenario 4: Multi-Stage Indexing with Different Log Levels**

Different stages may need different verbosity:

```bash
# Stage 1: Initial validation (verbose)
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --config data/config.json \
  --collection ecc-std \
  --persist-dir ./chroma \
  --e2e-test-run \
  --e2e-sample-size 100 \
  --log-file logs/stage1_validation.log \
  --log-level DEBUG

# Stage 2: Full indexing (normal verbosity)
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file logs/stage2_full_index.log \
  --log-level INFO \
  --log-max-bytes 209715200 \
  --log-backup-count 10
```

**Scenario 5: Monitoring Long-Running Jobs**

When indexing takes hours, monitor progress:

```bash
# Start indexing in background
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file logs/long_running.log \
  --log-no-console \
  > /dev/null 2>&1 &

# Save PID for later
echo $! > logs/indexing.pid

# Monitor progress in another terminal
tail -f logs/long_running.log | grep -E "(INFO|WARNING|ERROR)"

# Or watch specific metrics
watch -n 30 'tail -100 logs/long_running.log | grep "Indexed"'
```

#### Troubleshooting Log Issues

**Problem: Logs not appearing**

Check:
1. Directory permissions: `ls -ld logs/`
2. Disk space: `df -h`
3. Process is running: `ps aux | grep vectorize`

**Problem: Log files growing too fast**

Reduce log level or increase rotation:
```bash
# Less verbose
--log-level WARNING  # Only warnings and errors

# More aggressive rotation
--log-max-bytes 10485760  # 10 MB files
--log-backup-count 50     # More files, but smaller
```

**Problem: Need to grep across rotated logs**

```bash
# Search all current and rotated logs
grep "ERROR" logs/vectorize.log*

# Search with context
grep -C 5 "ValidationError" logs/vectorize.log*

# Count errors across all logs
grep -c "ERROR" logs/vectorize.log* | awk -F: '{sum+=$2} END {print sum}'
```

**Problem: Logs taking too much disk space**

Compress old rotated logs:
```bash
# Compress all backup logs
find logs/ -name "*.log.[0-9]*" -exec gzip {} \;

# Or use logrotate for automatic compression
cat > /etc/logrotate.d/vectorize <<EOF
/var/log/vectorize/*.log {
    size 100M
    rotate 10
    compress
    delaycompress
    missingok
    notifempty
}
EOF
```

#### Log Analysis Tips

**Extract performance metrics:**
```bash
# Find indexing rate
grep "Indexed" logs/vectorize.log | tail -20

# Calculate average time per partition
grep "partition.*completed" logs/vectorize.log | \
  awk '{print $NF}' | \
  awk '{sum+=$1; count++} END {print sum/count}'
```

**Identify bottlenecks:**
```bash
# Find slowest operations
grep "took" logs/vectorize.log | sort -k NF -n | tail -20

# Check for retries or failures
grep -E "(retry|failed|error)" logs/vectorize.log -i
```

**Monitor memory usage trends:**
```bash
# If you log memory stats
grep "memory" logs/vectorize.log | \
  awk '{print $timestamp, $memory_mb}' | \
  gnuplot -e "set terminal dumb; plot '-' using 1:2 with lines"
```
