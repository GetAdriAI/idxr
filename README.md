# Indexer Package Overview

**Indexer** captures the whole lifecycle of turning raw SAP ECC exports into a production-ready vector store. The package bundles two complementary CLIs—`prepare_datasets.py` and `vectorize.py`—plus shared libraries that handle schema management, data validation, partition manifests, resume metadata, and drop/remediation flows.

## Lifecycle in Three Acts

1. **Prepare** – `prepare_datasets.py` stubs configs, sanitises CSVs, deduplicates rows, and writes manifest-tracked partitions. It detects schema changes, versions them, and marks older partitions stale.
2. **Index** – `vectorize.py` streams validated partitions into Chroma (local or cloud), manages resume state, enforces batch token limits, and keeps partition-level persistence for incremental replays.
3. **Remediate** – Both tools support drop planning and application so you can retire stale data, purge partitions, or re-ingest after schema shifts without losing traceability.

## Feature Highlights

- 🔄 **Schema-aware manifest** with versioning, stale partition tracking, and per-model metadata.
- 🧠 **Resume-friendly ingestion** (per model and per partition) that records file offsets and row indices.
- 🩹 **CSV repair safeguards**; `prepare_datasets.py` stitches newline-fractured rows around a configured malformed column before deciding to drop them.
- ⚡ **Digest caches** keep reruns fast by persisting per-partition row hashes alongside the CSVs.
- 🗂️ **Pluggable collection strategies** let Chroma Cloud index each partition into its own collection while local runs stick with a single name.
- 🚮 **Stale cleanup parity** – when partitions map to standalone collections, `--delete-stale` drops those collections wholesale before rebuilding.
- 🎯 **E2E sampling mode** (`--e2e-test-run`) indexes random rows per CSV and writes an audit log so you can validate pipelines without processing millions of records.
- 🧩 **Pluggable model registries**; pass `--model <module:REGISTRY>` to target ECC defaults or your own knowledge domain.
- ☁️ **Chroma transport flexibility**; switch between persistent client and HTTP/Cloud with a couple of flags.
- 🧹 **Drop + remediation tooling** that mirrors the migration workflow and keeps audit history.

## Quick Start

```bash
# 1) Describe your registry target once
export MODEL_REGISTRY_TARGET="kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY"

# 2) Scaffold a dataset config
prepare_datasets.py new-config ecc-foundation --model "$MODEL_REGISTRY_TARGET"

# 3) Produce partitions (idempotent; MVCC-friendly)
prepare_datasets.py \
  --model "$MODEL_REGISTRY_TARGET" \
  --config configs/ecc_foundation.json \
  --output-root build/partitions

# 4) Index into Chroma and resume safely across runs
vectorize.py index \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --resume
```

Looking for deeper dives? Check out [`DOC.md`](DOC.md) for a narrative walkthrough and [`FAQ.md`](FAQ.md) for operational tips.
