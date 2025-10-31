# --truncation-strategy

**Why we added this flag:** different document shapes need different trimming strategies when they exceed token limits; this switch lets you pick the global default.

## What it does

- Sets the default truncation behaviour before embedding.
- Choices: `end`, `start`, `middle_out`, `sentences`, `auto` (default).
- Per-model overrides are possible via the vectorize config.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --truncation-strategy middle_out
```

## Tips

- Leave `auto` enabled until you understand your content mix; idxr chooses strategies based on schema hints.
- Switch to `middle_out` for highly structured tables so you keep both headers and footers.
- Monitor the logs—idxr reports truncation decisions along with token savings.
