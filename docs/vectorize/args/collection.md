# --collection

**Why we added this flag:** Chroma stores documents in named collections; idxr needs to know which collection to upsert into (or prefix when partitioning).

## What it does

- Identifies the target collection.
- Required for persistent client runs; optional for partition-aware Cloud runs where each partition uses its own collection name derived from metadata.
- Used when generating resume state filenames (`<collection>_resume_state.json`).

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --client-type cloud \
  --collection ecc-std
```

## Tips

- Namespace collections by environment (e.g., `kb-prod`, `kb-staging`) to simplify cross-env testing.
- When using partition-specific collections, include the base collection name in observability dashboards so metrics aggregate correctly.
