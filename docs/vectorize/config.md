# Vectorize Config Reference

When you index directly from raw CSVs instead of a partition manifest, `idxr vectorize` reads a JSON config that mirrors the prepare-datasets layout with a couple of vectorization-specific knobs.

```json
{
  "Contract": {
    "path": "datasets/contracts.csv",
    "columns": {
      "id": "CONTRACT_ID",
      "title": "CONTRACT_TITLE",
      "summary": "DESCRIPTION"
    },
    "truncation_strategy": "middle_out"
  }
}
```

> **Auto-generated**: If you run `idxr prepare_datasets new-config`, the companion vectorize config is scaffolded automatically. Use that stub as the starting point whenever possible.

| Field | Required | Description |
|-------|----------|-------------|
| `path` | ✅ | Source file path. Leave blank to skip a model temporarily. |
| `columns` | ✅ | Mapping of model field names to CSV headers. Should align with the prepare-datasets config. |
| `truncation_strategy` | optional | Override the truncation behaviour for this model (`end`, `start`, `middle_out`, `sentences`). Leave `null` for the global default. |

For partition-based pipelines you do **not** need this config—just point `idxr vectorize index` at the manifest emitted by `idxr prepare_datasets`.
