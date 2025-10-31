# --partition-manifest

**Why we added this flag:** partition-aware indexing needs to replay manifest “migrations” in order; this flag points vectorize at the manifest produced by `idxr prepare_datasets`.

## What it does

- Path to the `manifest.json` emitted by prepare-datasets.
- Determines which partitions to index, in which order, and with which schema version metadata.
- Mutually exclusive with `--config`; choose manifest-driven or direct CSV configs.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --collection ecc-std
```

## Tips

- Keep the manifest under version control for auditability.
- If you want to replay a subset, copy the manifest, edit the partitions list, and point the command at the trimmed copy.
