# --partition-dir

**Why we added this flag:** the status command needs to read partition metadata even when the manifest is unavailable; this flag lets you point directly at the partition directory tree.

## What it does

- Path to the folder containing partition subdirectories (typically the same `--output-root` used during preparation).
- Used by `idxr vectorize status` to compare manifest entries against indexed outputs.
- Optional when the manifest is accessible; required otherwise.

## Typical usage

```bash
idxr vectorize status \
  --model "$IDXR_MODEL" \
  --partition-dir workdir/partitions \
  --partition-out-dir workdir/chroma_partitions
```

## Tips

- Pair with `--partition-out-dir` to get a concise summary of which partitions have completed indexing.
- Include the status command in CI to fail fast when an indexing job leaves partitions partially processed.
