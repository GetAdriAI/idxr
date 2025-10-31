# --model

**Why we added this flag:** vectorization must use the same model registry as prepare-datasets to ensure metadata alignment and schema validation.

## What it does

- Accepts a Python import path (`package.module:ATTRIBUTE`) resolving to a `Mapping[str, ModelSpec]`.
- Drives per-model token policies, metadata enrichment, and schema signature validation during indexing.
- Required for every `idxr vectorize` command.

## Typical usage

```bash
idxr vectorize index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions
```

## Tips

- Keep a shared environment variable (`IDXR_MODEL`) so all automation references the same registry string.
- If you maintain multiple registries, note them in your manifest to avoid mixing incompatible partitions.
