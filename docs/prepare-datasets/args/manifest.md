# --manifest

**Why we added this flag:** reruns need continuity—by pointing at an existing manifest, idxr layers new partitions on top of the previous history instead of overwriting it.

## What it does

- Allows you to reuse an existing manifest (`manifest.json`) rather than letting idxr create a fresh one under the output root.
- Handy when two configs contribute to the same manifest (e.g., a hotfix layered onto a full export).
- Optional; if omitted, idxr defaults to `<output-root>/manifest.json`.

## Typical usage

```bash
idxr prepare_datasets \
  --model "$IDXR_MODEL" \
  --config configs/hotfix.json \
  --output-root workdir/partitions \
  --manifest workdir/partitions/manifest.json
```

## Tips

- Always back up the manifest before large migrations; it is the authoritative history of processed rows.
- When experimenting, target a separate manifest (e.g., under `workdir/sandboxes`) to avoid contaminating production history.
