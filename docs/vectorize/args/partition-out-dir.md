# --partition-out-dir

**Why we added this flag:** each partition needs a durable home for embedding state, logs, and error payloads; this flag declares the root directory for index artifacts.

## What it does

- Directory where per-partition resume files, error YAMLs, and compacted documents are stored.
- Required for manifest-driven indexing. Can be used with `--persist-dir` for local Chroma or implicitly with cloud clients.
- Reusing the same directory allows `--resume` to pick up unfinished partitions.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --resume
```

## Tips

- Keep this directory on a fast, reliable volume; idxr writes incremental checkpoints frequently.
- Rotate old partitions by archiving subdirectories once the manifest marks them as complete or dropped.
