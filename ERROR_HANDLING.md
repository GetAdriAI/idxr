# Error Handling and Recovery Guide

This guide explains how the indexer handles API failures, what happens when things go wrong, and how to recover from errors during large-scale indexing operations.

## Table of Contents

- [Critical Behavior: Fail-Stop Architecture](#critical-behavior-fail-stop-architecture)
- [What Happens When API Calls Fail](#what-happens-when-api-calls-fail)
- [Error Reports](#error-reports)
- [Resume and Recovery](#resume-and-recovery)
- [Practical Scenarios](#practical-scenarios)
- [Mitigation Strategies](#mitigation-strategies)
- [Troubleshooting Common Failures](#troubleshooting-common-failures)

---

## Critical Behavior: Fail-Stop Architecture

### ⚠️ The Indexer Uses a Fail-Stop Design

When an API call fails (ChromaDB or OpenAI), **the entire partition stops immediately**. The indexer does NOT:
- ❌ Continue with other records in the batch
- ❌ Continue with other batches in the model
- ❌ Continue with other models in the partition
- ❌ Continue with other partitions

**However, it does ensure:**
- ✅ All previously indexed batches remain in ChromaDB
- ✅ Resume state is saved after each successful batch
- ✅ Detailed error reports are written to disk
- ✅ Clean recovery is possible with `--resume`

---

## What Happens When API Calls Fail

### ChromaDB API Failures

When a call to `collection.upsert()` fails, the following sequence occurs:

**Source:** `indexer/vectorize_lib/indexing.py:604-654`

```python
try:
    collection.upsert(
        ids=emitted_ids,
        documents=emitted_docs,
        metadatas=emitted_metas,
    )
except Exception as exc:
    # 1. Write detailed error report to disk
    error_path = _write_error_report(
        error_dir=error_dir,
        model_name=model_key,
        collection_name=collection_name,
        reason=reason,
        source_csv=source_csv,
        emitted_ids=emitted_ids,
        emitted_docs=emitted_docs,
        emitted_metas=emitted_metas,
        emitted_rows=emitted_rows,
        token_counts=emitted_tokens,
        token_total=emitted_token_total,
        resume_state=state_ref,
        exception=exc,
        traceback_text=traceback_text,
    )

    # 2. Log the failure with full context
    logging.exception(
        "Chroma upsert failed for model %s (csv=%s, reason=%s). Rows: %s",
        model_key,
        source_csv,
        reason,
        context_summary,
    )

    # 3. Log error report location
    if error_path is not None:
        logging.error("Error report persisted to %s", error_path)

    # 4. Re-raise the exception (STOPS EVERYTHING)
    raise
```

### OpenAI API Failures

OpenAI embedding API calls happen **inside** ChromaDB's `collection.upsert()`. When the OpenAI API fails:

1. ChromaDB's embedding function encounters the error
2. ChromaDB propagates the exception
3. The exception is caught by the handler above
4. Same fail-stop behavior occurs

**Common OpenAI failures:**
- `RateLimitError` - Too many requests per minute
- `APIConnectionError` - Network timeout or connection issues
- `APIError` - OpenAI service errors
- `AuthenticationError` - Invalid API key
- `InvalidRequestError` - Malformed request (e.g., token limit exceeded)

---

## Error Reports

### Location

Error reports are saved to:
```
<partition-out-dir>/<partition-name>/errors/<model-name>_<timestamp>.(yaml|json)
```

**Example:**
```
build/vector/partition_0005/errors/Table_20251030_153045.yaml
```

### Contents

Each error report contains complete information needed for debugging:

```yaml
# Model and collection context
model_name: Table
collection_name: ecc-std
reason: threshold-reached  # Why this batch was being flushed
source_csv: /data/tables.csv

# Batch details
batch_size: 50
document_ids:
  - "Table:a1b2c3d4e5f67890"
  - "Table:f1e2d3c4b5a67890"
  # ... all IDs in the failed batch

# Document content (first 1000 chars per document)
documents:
  - "MARA - Materials Management\nTable for material master..."
  - "MARC - Plant Data for Material\nStorage location data..."

# Metadata for each document
metadatas:
  - model_name: Table
    keyword_field_1: value1
    keyword_field_2: value2
  - model_name: Table
    keyword_field_1: value3

# Row tracking
row_numbers: [1001, 1002, 1003, ...]  # Original CSV row numbers

# Token information
token_counts: [150, 200, 175, ...]  # Tokens per document
token_total: 7500  # Total tokens in this batch

# Resume state (for recovery)
resume_state:
  offset: 5242880  # Byte offset in CSV file
  row_index: 1000  # Last successfully indexed row
  fieldnames: ['TABNAME', 'DDTEXT', ...]  # CSV columns

# Exception details
exception_type: APIConnectionError
exception_message: "Connection to api.openai.com timed out"
traceback: |
  Traceback (most recent call last):
    File "indexer/vectorize_lib/indexing.py", line 554
    ...
  Full Python traceback

# Timestamp
timestamp: "2025-10-30T15:30:45Z"
```

### Inspecting Error Reports

```bash
# List all error reports
find build/vector -name "*.yaml" -path "*/errors/*" -type f

# View most recent error
ls -t build/vector/*/errors/*.yaml | head -1 | xargs cat

# Count errors by model
find build/vector -name "*.yaml" -path "*/errors/*" -exec basename {} \; | \
  cut -d_ -f1 | sort | uniq -c

# Check errors for specific partition
cat build/vector/partition_0005/errors/Table_*.yaml
```

---

## Resume and Recovery

### How Resume State Works

After each successful batch, the indexer saves progress:

**Source:** `indexer/vectorize_lib/indexing.py:673-679`

```python
# After successful upsert
persist_state(
    False,  # complete=False (not done yet)
    documents_indexed=added,
    collection_total=collection_count_so_far,
    signature=signature,
    state=state_ref,
)
```

**Resume state location:**
```
<partition-out-dir>/<partition-name>/<collection-name>_resume_state.json
```

**Example:**
```json
{
  "Table": {
    "complete": false,
    "indexed_at": "2025-10-30T15:30:00",
    "documents_indexed": 500000,
    "collection_count": 500000,
    "source_signature": {
      "mtime": 1730304600.0,
      "size": 524288000
    },
    "started": true,
    "file_offset": 52428800,
    "row_index": 500000,
    "fieldnames": ["TABNAME", "DDTEXT", "TABCLASS"]
  },
  "Field": {
    "complete": true,
    "indexed_at": "2025-10-30T14:00:00",
    "documents_indexed": 2000000,
    "collection_count": 2000000,
    "source_signature": {
      "mtime": 1730300400.0,
      "size": 2147483648
    },
    "started": true
  }
}
```

### Recovery with --resume

When you run with `--resume` after a failure:

1. **Loads resume state** (or empty dict if missing)
2. **Scans ChromaDB** for models with missing/incomplete state
3. **Skips completed models** (unchanged CSV files)
4. **Resumes from last successful batch** (using file offset or row count)
5. **Continues indexing** where it left off

```bash
# Resume after failure
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --resume \
  --log-file logs/resume.log
```

**What happens:**
- ✅ Partitions with `complete: true` for all models → skipped entirely
- ✅ Partitions with failed models → resumed from last good batch
- ✅ Failed batch → retried with fresh API calls
- ✅ Subsequent batches → processed normally

### No Resume State File? No Problem!

If the program crashes before creating a resume state file, `--resume` still works:

1. Detects all models have missing state
2. Scans the ChromaDB collection to count existing documents
3. Uses collection counts to determine where to resume
4. Creates resume state file for future runs

**Source:** `indexer/vectorize_lib/indexing.py:219-266`

---

## Practical Scenarios

### Scenario 1: Indexing 16 Million Records - ChromaDB Cloud Timeout

**Setup:**
- 16M records split into 10 partitions (1.6M each)
- Batch size: 1000
- Processing partition 5
- 500 batches completed successfully (500k records indexed)

**Failure:**
- Batch 501 fails with `APIConnectionError: Connection timeout`
- Program crashes immediately

**State after failure:**
```
✅ Partitions 1-4: Complete (6.4M records in ChromaDB)
✅ Partition 5: 500k records in ChromaDB, resume state saved at row 500,000
❌ Partition 5: Batch 501 failed, 1000 records NOT uploaded
❌ Partition 5: Remaining 1.1M records NOT processed
❌ Partitions 6-10: NOT started (6.4M records NOT processed)
```

**Error report:**
```
build/vector/partition_0005/errors/Table_20251030_153045.yaml
```

**Recovery:**
```bash
# Check the error
cat build/vector/partition_0005/errors/Table_*.yaml

# Resume indexing
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --resume \
  --log-file logs/retry.log
```

**What resume does:**
1. Skips partitions 1-4 (complete)
2. Resumes partition 5 from row 500,000
3. Retries batch 501 (the failed batch)
4. Continues with batches 502-1600
5. Processes partitions 6-10

### Scenario 2: OpenAI Rate Limit Exceeded

**Failure:**
```
openai.error.RateLimitError: Rate limit exceeded. Please retry after 20 seconds.
```

**What happens:**
- Current batch fails
- Error report saved with full rate limit details
- Indexing stops

**Recovery strategy:**
```bash
# Wait for rate limit to reset
sleep 30

# Resume with smaller batch size to reduce rate
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --batch-size 50 \
  --resume \
  --log-file logs/after_rate_limit.log
```

### Scenario 3: Network Interruption During Parallel Partition Processing

**Setup:**
```bash
vectorize.py index \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --parallel-partitions 4 \
  --log-file logs/parallel.log
```

**Failure:**
- Worker processing partition 3 encounters network timeout
- Workers for partitions 1, 2, 4 continue running
- Worker 3 crashes and raises exception

**What happens:**
```
✅ Partition 1: Completes successfully
✅ Partition 2: Completes successfully
❌ Partition 3: Fails mid-way, resume state saved
✅ Partition 4: Completes successfully
⚠️  Main process: Exits with error code 1 due to partition 3 failure
```

**Recovery:**
```bash
# Resume will only process partition 3
vectorize.py index \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --resume \
  --log-file logs/retry_partition3.log
```

---

## Mitigation Strategies

### 1. Use Smaller Partitions

Reduce the blast radius of failures by creating more, smaller partitions:

```bash
# In prepare_datasets.py
poetry run python indexer/prepare_datasets.py prepare \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --input-dir data/raw \
  --output-dir build/partitions \
  --max-partition-rows 100000 \
  --manifest build/partitions/manifest.json
```

**Benefits:**
- Smaller partitions complete faster
- Less work lost if a partition fails
- More granular progress tracking
- Easier to identify problematic data

**Trade-offs:**
- More partition directories
- Slightly more overhead per partition

### 2. Enable Parallel Processing with Automatic Retry

Process multiple partitions simultaneously to maximize throughput:

```bash
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --parallel-partitions 4 \
  --resume \
  --log-file logs/parallel.log
```

**With automatic retry wrapper:**

```bash
#!/bin/bash
# retry_index.sh

MAX_RETRIES=5
RETRY_COUNT=0
RETRY_DELAY=60  # seconds

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    echo "Indexing attempt $((RETRY_COUNT + 1)) of $MAX_RETRIES"

    poetry run python indexer/vectorize.py index \
        --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
        --partition-manifest build/partitions/manifest.json \
        --partition-out-dir build/vector \
        --collection ecc-std \
        --parallel-partitions 4 \
        --resume \
        --log-file "logs/attempt_${RETRY_COUNT}.log"

    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        echo "✅ Indexing completed successfully!"
        exit 0
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))

    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        echo "⚠️  Attempt $RETRY_COUNT failed (exit code $EXIT_CODE)"
        echo "⏳ Retrying in ${RETRY_DELAY} seconds..."
        sleep $RETRY_DELAY

        # Exponential backoff
        RETRY_DELAY=$((RETRY_DELAY * 2))
    fi
done

echo "❌ Failed after $MAX_RETRIES attempts"
exit 1
```

### 3. Monitor and Alert

Track indexing progress with real-time monitoring:

```bash
#!/bin/bash
# monitor_progress.sh

LOG_FILE="logs/vectorize.log"
CHECK_INTERVAL=30  # seconds

echo "Monitoring indexing progress..."
echo "Press Ctrl+C to stop monitoring"
echo ""

LAST_BATCH=0
LAST_TIME=$(date +%s)

while true; do
    # Count successful batches
    CURRENT_BATCH=$(grep -c "Indexed.*batch" "$LOG_FILE" 2>/dev/null || echo 0)

    # Calculate rate
    CURRENT_TIME=$(date +%s)
    TIME_DIFF=$((CURRENT_TIME - LAST_TIME))
    BATCH_DIFF=$((CURRENT_BATCH - LAST_BATCH))

    if [ $TIME_DIFF -gt 0 ]; then
        RATE=$(echo "scale=2; $BATCH_DIFF / $TIME_DIFF * 60" | bc)
    else
        RATE="0"
    fi

    # Check for errors
    ERROR_COUNT=$(grep -c "ERROR" "$LOG_FILE" 2>/dev/null || echo 0)

    # Display status
    echo "$(date '+%Y-%m-%d %H:%M:%S') | Batches: $CURRENT_BATCH | Rate: ${RATE} batches/min | Errors: $ERROR_COUNT"

    # Check if process is still running
    if ! pgrep -f "vectorize.py index" > /dev/null; then
        echo ""
        echo "⚠️  Indexing process not running!"

        # Check exit status
        if tail -1 "$LOG_FILE" | grep -q "Completed indexing"; then
            echo "✅ Process completed successfully"
        else
            echo "❌ Process may have crashed - check logs"
            echo "📁 Error reports: $(find build/vector -name "*.yaml" -path "*/errors/*" | wc -l)"
        fi
        exit 1
    fi

    LAST_BATCH=$CURRENT_BATCH
    LAST_TIME=$CURRENT_TIME

    sleep $CHECK_INTERVAL
done
```

### 4. Use Rate Limiting for API Calls

Reduce batch size to stay under API rate limits:

```bash
# Conservative settings for high rate limit sensitivity
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --batch-size 50 \
  --resume \
  --log-file logs/conservative.log
```

**Batch size considerations:**
- Smaller batches = more API calls = higher chance of rate limits
- Larger batches = fewer API calls = more tokens per call
- Sweet spot typically: 100-500 documents per batch

### 5. Pre-Validate Your Data

Run a smoke test before full indexing:

```bash
# Test with small sample
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector_test \
  --collection ecc-std-test \
  --e2e-test-run \
  --e2e-sample-size 100 \
  --e2e-output build/test_samples.json \
  --log-file logs/validation.log
```

This validates:
- ✅ CSV files are readable
- ✅ Data passes Pydantic validation
- ✅ API credentials work
- ✅ Network connectivity is stable
- ✅ Token limits are respected

---

## Troubleshooting Common Failures

### ChromaDB Connection Errors

**Symptoms:**
```
chromadb.errors.ConnectionError: Unable to connect to ChromaDB server
```

**Causes:**
- ChromaDB server not running (for HTTP mode)
- Wrong host/port configuration
- Network firewall blocking connections
- ChromaDB Cloud authentication issues

**Solutions:**

```bash
# Check ChromaDB server status (HTTP mode)
curl http://localhost:8000/api/v1/heartbeat

# Verify environment variables
echo $CHROMA_SERVER_HOST
echo $CHROMA_SERVER_PORT
echo $CHROMA_API_TOKEN

# Test with persistent client instead
vectorize.py index \
  --client-type persistent \
  --persist-dir ./chroma_local \
  --collection ecc-std-local \
  --resume \
  --log-file logs/local.log
```

### OpenAI API Rate Limits

**Symptoms:**
```
openai.error.RateLimitError: Rate limit exceeded
```

**Causes:**
- Too many requests per minute (RPM)
- Too many tokens per minute (TPM)
- Concurrent indexing jobs sharing same API key

**Solutions:**

```bash
# Reduce batch size
--batch-size 50

# Use serial partition processing (not parallel)
# Remove --parallel-partitions flag

# Add delays between retries
sleep 60 && vectorize.py index --resume ...

# Check your OpenAI rate limits
curl https://api.openai.com/v1/me \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

### Token Limit Exceeded

**Symptoms:**
```
ERROR Skipping document Table:abc123...: 12500 tokens exceed hard API limit 8191
```

**Causes:**
- Single document exceeds maximum tokens
- Usually long text fields (descriptions, documentation)

**Solutions:**

1. **Reduce document size at source** - truncate long fields in CSV
2. **Adjust semantic fields** - exclude very long fields from indexing
3. **Document will be skipped** - logged but indexing continues for other docs

### Duplicate ID Errors

**Symptoms:**
```
chromadb.errors.DuplicateIDError: IDs already exist
```

**Causes:**
- Resume logic detected existing documents
- Collection was not properly cleaned before re-indexing

**What the indexer does:**
1. Detects duplicate IDs from exception
2. Filters them out automatically
3. Retries upsert with remaining documents
4. Logs warning about duplicates

**No action needed** - this is handled automatically.

### Out of Memory Errors

**Symptoms:**
```
MemoryError: Unable to allocate array
```

**Causes:**
- Batch size too large
- Partition has too many records
- Parallel workers consuming too much memory

**Solutions:**

```bash
# Reduce batch size
--batch-size 100

# Reduce parallel workers
--parallel-partitions 2

# Use smaller partitions
# Re-run prepare_datasets.py with --max-partition-rows 50000
```

### CSV Encoding Errors

**Symptoms:**
```
UnicodeDecodeError: 'utf-8' codec can't decode byte
```

**Causes:**
- CSV file not in UTF-8 encoding
- Binary data in CSV fields

**Solutions:**

```bash
# Check file encoding
file -bi data/tables.csv

# Convert to UTF-8
iconv -f ISO-8859-1 -t UTF-8 data/tables.csv > data/tables_utf8.csv

# Or specify encoding in prepare_datasets.py if supported
```

---

## Summary Table: Error Behavior

| Failure Type | Current Batch | Remaining Batches | Other Models | Other Partitions | Resume Works? |
|--------------|---------------|-------------------|--------------|------------------|---------------|
| ChromaDB API error | ❌ Lost | ❌ Not processed | ❌ Skipped | ❌ Skipped | ✅ Yes |
| OpenAI API error | ❌ Lost | ❌ Not processed | ❌ Skipped | ❌ Skipped | ✅ Yes |
| Network timeout | ❌ Lost | ❌ Not processed | ❌ Skipped | ❌ Skipped | ✅ Yes |
| Rate limit | ❌ Lost | ❌ Not processed | ❌ Skipped | ❌ Skipped | ✅ Yes (wait first) |
| Token limit (single doc) | ⚠️ Doc skipped | ✅ Continue | ✅ Continue | ✅ Continue | ✅ N/A |
| Duplicate IDs | ⚠️ Auto-filtered | ✅ Continue | ✅ Continue | ✅ Continue | ✅ N/A |
| CSV encoding error | ❌ Lost | ❌ Not processed | ❌ Skipped | ❌ Skipped | ❌ Fix file first |

**Key Takeaways:**
- Most API failures → Fail-stop → Resume to recover
- Token/duplicate issues → Auto-handled → No intervention needed
- Data quality issues → Fix source data → Re-run

---

## Best Practices

1. **Always use `--resume`** for production runs
2. **Enable file logging** to preserve error context
3. **Start with e2e test** to validate before full run
4. **Use smaller partitions** for large datasets
5. **Monitor error reports** directory for issues
6. **Implement retry logic** with exponential backoff
7. **Check resume state files** to track progress
8. **Keep API keys secure** and rotate regularly

---

## Additional Resources

- [DOC.md](DOC.md) - Main documentation
- [README.md](README.md) - Quick start guide
- `indexer/vectorize_lib/indexing.py` - Error handling implementation
- `indexer/vectorize_lib/utils.py` - Resume state utilities
