# --resume

**Why we added this flag:** large indexing jobs rarely finish in a single attempt; resume mode skips already processed rows so restarts are cheap.

## What it does

- Tells idxr to read the resume state file and skip models/partitions that have not changed.
- Works for both config-driven and manifest-driven runs.
- Automatically updates the resume state file after each successful model/partition.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --resume
```

## Tips

- Resume state is stored next to `--persist-dir`/`--partition-out-dir`. Back it up before big upgrades.
- Combine with `--batch-size` tuning to recover faster after transient API failures.
