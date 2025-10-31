# --log-file

**Why we added this flag:** long-running indexing jobs deserve persistent logs with rotation; this flag activates file logging alongside (or instead of) console output.

## What it does

- When provided, idxr writes logs to the specified path using rotating file handlers.
- Supports dynamic filenames (e.g., timestamped) to separate individual runs.
- Pair with `--log-max-bytes`, `--log-backup-count`, and `--log-no-console` for full control.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --log-file workdir/logs/vectorize.log \
  --log-max-bytes 209715200 \
  --log-level INFO
```

## Tips

- Use absolute paths when running under systemd or cron so logs land where you expect.
- Combine with log rotation (below) to prevent disk bloat on permanent ingestion workers.
