# --parallel-partitions

**Why we added this flag:** when manifests contain many partitions, running them sequentially can take hours; limited parallelism keeps throughput high while respecting API quotas.

## What it does

- Controls how many partitions idxr indexes concurrently (default: `1`).
- Only applies to manifest-driven runs.
- Each worker maintains its own resume state to ensure idempotency.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --parallel-partitions 4
```

## Tips

- Match the value to your embedding API rate limits. Start with `2` and scale up while monitoring throttling.
- Ensure the machine hosting idxr has enough CPU and memory—each partition spawns its own worker thread.
