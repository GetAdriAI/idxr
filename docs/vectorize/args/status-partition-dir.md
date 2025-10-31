# status --partition-dir

**Why we added this flag:** sometimes the manifest is unavailable, but the partition directory tree still exists; status can scan it directly when you provide this path.

## What it does

- Points `idxr vectorize status` at the directory containing partition subfolders and `vectorize_config.json` files.
- Optional but recommended; it reveals partitions that were configured yet never indexed.
- Complements `--partition-out-dir`, which inspects the output side of the pipeline.

## Typical usage

```bash
idxr vectorize status \
  --model "$IDXR_MODEL" \
  --partition-dir workdir/partitions \
  --partition-out-dir workdir/chroma_partitions
```

## Tips

- Provide both directories to cross-check configured vs. completed partitions.
- Handy for post-mortem scripts validating that every expected model reached the index.
