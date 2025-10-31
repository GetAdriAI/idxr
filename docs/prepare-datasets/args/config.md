# --config

**Why we added this flag:** idxr needs a concrete mapping between models and source files; the config flag lets you point to that JSON document each time you run the pipeline.

## What it does

- Path to the prepare-datasets JSON config (see [Config Reference](../config.md)).
- Required so idxr knows which source files to read and how to map columns.
- Supports relative paths; they are resolved from the current working directory.

## Typical usage

```bash
idxr prepare_datasets \
  --model "$IDXR_MODEL" \
  --config workdir/configs/prepare_datasets_contracts.json \
  --output-root workdir/partitions
```

## Tips

- Keep configs under `workdir/prepare_datasets` (or similar) so they are easy to diff in Git.
- Use different configs for full exports vs. patch drops to keep manifests easy to audit.
