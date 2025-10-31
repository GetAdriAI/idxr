# --model

**Why we added this flag:** every dataset run needs to know which Pydantic model registry to validate against; making it explicit avoids accidentally targeting the wrong schema bundle.

## What it does

- Accepts a Python import string (`package.module:ATTRIBUTE`) that resolves to a mapping of model names to `ModelSpec` objects.
- Drives schema validation, field listing, and schema signature hashing for manifest tracking.
- Required for all `idxr prepare_datasets` invocations.

## Typical usage

```bash
idxr prepare_datasets \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --config configs/hotfix.json \
  --output-root build/partitions
```

## Tips

- Reference the same registry for prepare and vectorize so schema signatures stay aligned.
- Use environment variables if you switch registries frequently: `export IDXR_MODEL=kb.std...` and pass `--model "$IDXR_MODEL"`.
