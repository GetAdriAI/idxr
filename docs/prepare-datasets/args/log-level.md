# --log-level

**Why we added this flag:** long-running jobs need adjustable verbosity for debugging; this switch lets you promote or suppress log noise without editing code.

## What it does

- Sets the root logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
- Defaults to `INFO`.
- Works with both console output and file handlers configured via environment variables.

## Typical usage

```bash
idxr prepare_datasets \
  --model "$IDXR_MODEL" \
  --config configs/full_export.json \
  --output-root workdir/partitions \
  --log-level DEBUG
```

## Tips

- Use `DEBUG` when investigating malformed rows; the log stream includes row indices and remediation actions.
- Keep production runs at `INFO` or higher to avoid massive log files.
