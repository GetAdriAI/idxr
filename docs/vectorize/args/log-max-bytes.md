# --log-max-bytes

**Why we added this flag:** when file logging is enabled, we need a cap on file size so long-running jobs do not fill disks.

## What it does

- Defines the rotation threshold (in bytes) for the log file handler.
- Defaults to `104857600` (100 MB).
- Only relevant when `--log-file` is set.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --log-file workdir/logs/vectorize.log \
  --log-max-bytes 209715200
```

## Tips

- Pair with `--log-backup-count` to define total retained log size.
- Tune based on infrastructure—smaller caps rotate more frequently but may split stack traces across files.
