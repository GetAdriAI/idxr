# --output-root

**Why we added this flag:** partition outputs and manifests belong in a predictable workspace so they can be shared with vectorize; this flag names that root directory.

## What it does

- Specifies where idxr should create partition directories and the `manifest.json`.
- Required for every run; idxr creates the directory if it does not exist.
- Using the same output root across runs lets idxr append new partitions and reuse digests.

## Typical usage

```bash
idxr prepare_datasets \
  --model "$IDXR_MODEL" \
  --config configs/hotfix.json \
  --output-root workdir/partitions
```

## Tips

- Commit the manifest file to source control to capture a history of migrations.
- Keep the output root outside of your source tree if partitions are large; symlink the manifest back into Git if needed.
