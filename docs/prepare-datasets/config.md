# Prepare Dataset Config Reference

`idxr prepare_datasets` consumes a JSON document that maps each Pydantic model name to a preprocessing recipe. A minimal config looks like:

```json
{
  "Contract": {
    "path": "datasets/contracts.csv",
    "columns": {
      "id": "CONTRACT_ID",
      "title": "CONTRACT_TITLE",
      "summary": "DESCRIPTION"
    },
    "character_encoding": "utf-8",
    "delimiter": ",",
    "malformed_column": null,
    "header_row": "all",
    "drop_na_columns": []
  }
}
```

Each field plays a specific role during preprocessing:

| Field | Required | Description |
|-------|----------|-------------|
| `path` | ✅ | Absolute or relative path to the source CSV/JSONL file. Leave blank (`""`) to skip a model temporarily. |
| `columns` | ✅ | Mapping of model field name → source column header. Add, remove, or rename entries to match the schema expected by the Pydantic model. |
| `character_encoding` | optional (defaults to `"utf-8"`) | Target encoding for the dataset. idxr decodes using this value and re-encodes output partitions as UTF-8. |
| `delimiter` | optional (defaults to `","`) | Column delimiter for CSV inputs. Change to `"\t"` for TSV or `";"` if your exports use semicolons. |
| `malformed_column` | optional | Zero-based index of a column that frequently contains embedded newlines. idxr stitches rows by looking ahead until it can parse this column. |
| `header_row` | optional (defaults to `"all"`) | Controls which rows are considered headers: `"all"` keeps every header row, `"first"` retains only the first row, or specify a literal string to match. |
| `drop_na_columns` | optional (defaults to `[]`) | List of column names that must be non-empty. Rows with empty/`NaN` values in these columns are dropped before partitioning. |

### Tips

- Store configs under version control. They serve as the contract between data engineering and knowledge engineering teams.
- When CSV exports move, update just the `path`—manifest diffing prevents reprocessing unchanged rows.
- Use separate configs for different sourcing strategies (e.g., nightly full export vs. targeted hotfix).
