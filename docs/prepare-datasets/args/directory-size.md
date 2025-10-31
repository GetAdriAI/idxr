# --directory-size

**Why we added this flag:** large exports can overwhelm filesystem limits; directory sizing caps how many rows a partition may contain so runs stay manageable.

## What it does

- Sets the maximum number of rows per model per partition directory.
- `0` (default) means unlimited rows; any positive integer enforces a split.
- Useful when chunking massive tables for parallel indexing or archiving.

## Typical usage

```bash
idxr prepare_datasets \
  --model "$IDXR_MODEL" \
  --config configs/full_export.json \
  --output-root workdir/partitions \
  --directory-size 500000
```

## Tips

- Match the partition size to the throughput of your vectorization job—smaller chunks resume faster after failures.
- Monitor manifest growth; each new directory is recorded with schema and timestamp metadata.
