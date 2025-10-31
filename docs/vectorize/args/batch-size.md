# --batch-size

**Why we added this flag:** embedding APIs have rate and token limits; controlling batch size lets you trade throughput for stability.

## What it does

- Sets the maximum number of documents per embedding request (default: `128`).
- Works alongside `--token-limit` to prevent oversized batches.
- Smaller batches reduce retry storms when your model registry contains very large documents.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --batch-size 300 \
  --truncation-strategy middle_out
```

## Tips

- Increase cautiously—monitor OpenAI rate limits and Chroma ingest timing.
- Pair with `--parallel-partitions` to achieve higher concurrency without breaching per-request limits.
