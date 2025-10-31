# Overview

idxr packages the full lifecycle of an operational vector index into a repeatable playbook. The toolkit is **model-centric**—you describe data with Pydantic models, **config-driven**—you check configs into source control, and **fail-stop-retry**—every stage records checkpoints so restarts are safe.

## Lifecycle at a Glance

1. **Create the First Index**  
   Use your model registry to scaffold preprocessing and vectorization configs. Generate partitions, hydrate an index, and lock the manifest snapshot in Git.

2. **Feed the Pipeline Daily**  
   As new data lands, rerun `idxr prepare_datasets` against the same config. Digest caches and row fingerprints keep subsequent runs fast while appending only novel partitions.

3. **Add New Models with Confidence**  
   New business areas slot in by registering fresh Pydantic models. Regenerate configs for those models only, review the diffs, and let idxr blend them into the same manifest.

4. **Evolve Schemas Safely**  
   Schema changes version themselves. When fields are added or renamed, idxr marks older partitions as stale and replays only the affected slices on the next vectorization run.

5. **Operate with Guardrails**  
   Every long-running job writes resumable state, detailed logs, and YAML error payloads for failed batches. You fix the source issue, rerun with `--resume`, and idxr carries on from the last good batch.

## Components

- `idxr prepare_datasets` – partitions raw CSVs/JSONL, normalises encodings, and keeps a manifest of partition “migrations”.
- `idxr vectorize` – streams partitions into Chroma (local or cloud), enforces token budgets, and supports multi-partition concurrency.
- Shared libraries – offer model registries, manifest utilities, truncation strategies, drop orchestration, and logging helpers.

This documentation dives into each phase, explains every configuration surface, and links practical command-line recipes for daily operations. Continuous delivery of your knowledge base starts here.
