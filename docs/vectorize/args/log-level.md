# --log-level

**Why we added this flag:** vectorization spans long network calls; adjustable verbosity helps distinguish steady-state noise from actionable errors.

## What it does

- Sets the logging verbosity for all subcommands (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
- Defaults to `INFO`.
- Works with both console and file handlers.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --log-level INFO
```

## Tips

- Switch to `DEBUG` during incident response; revert to `INFO` for production to limit log volume.
- Combine with `--log-no-console` when running in environments where STDOUT is noisy or rate-limited.
