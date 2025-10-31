# --config

**Why we added this flag:** when you index straight from CSVs (without using prepare-datasets), you still need a declarative mapping—this flag points vectorize to that JSON config.

## What it does

- Path to the vectorize config file (see [Config Reference](../config.md)).
- Mutually exclusive with `--partition-manifest`. Choose one source of truth.
- Required for direct CSV indexing; optional otherwise.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --config configs/vectorize_contracts.json \
  --collection ecc-std \
  --persist-dir workdir/chroma
```

## Tips

- Prefer manifest-driven indexing in production; use config-driven runs for quick experiments or backfills.
- Keep vectorize and prepare-datasets configs in sync so column renames stay consistent.
