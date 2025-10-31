# Prepare Datasets

`idxr prepare_datasets` turns raw CSV/JSONL exports into manifest-tracked partitions. It is the “migration authoring” phase of the lifecycle—you build reproducible input slices that downstream vectorization can replay in order.

## Responsibilities

1. **Schema awareness** – uses your Pydantic model registry to validate column mappings and detect schema drift.
2. **Row hygiene** – trims whitespace, fixes malformed encodings, stitches newline-leaking rows, and drops duplicates via deterministic digests.
3. **Partition orchestration** – writes partitions into timestamped directories while maintaining a single manifest that records model, partition, and schema version metadata.
4. **Change tracking** – records row-level digests alongside the manifest so reruns skip previously processed records.
5. **Drop planning** – generates and applies remediation scripts that mark partitions as stale or deleted when you want to unwind a bad migration.

## Workflow Summary

1. **Scaffold a config** with `idxr prepare_datasets new-config`. The config lists every model and generates a column mapping stub.
2. **Edit the config** to point at the CSV exports you actually want to ingest.
3. **Run `idxr prepare_datasets`** with the config and an output directory. Repeated runs append new partitions if the source data changed.
4. **Review the manifest** (`manifest.json`) to audit what was produced, including digests and schema signatures.
5. **Plan drops** with `idxr prepare_datasets plan-drop` and execute them with `idxr prepare_datasets apply-drop` whenever you need to roll back a migration.

The rest of this section documents the configuration schema and command-line surface area so you can tailor the pipeline to your own datasets.
