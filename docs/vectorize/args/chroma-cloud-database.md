# --chroma-cloud-database

**Why we added this flag:** Chroma Cloud segregates data into databases within a tenant; the database header ensures idxr writes to the intended logical database.

## What it does

- Specifies the database identifier when `--client-type=cloud`.
- Sets the `X-Chroma-Database` header on every request.
- Required for Chroma Cloud runs; ignored elsewhere.

## Typical usage

```bash
idxr vectorize index \
  --client-type cloud \
  --chroma-cloud-tenant tenant_id \
  --chroma-cloud-database db_name \
  --chroma-api-token ck-XXXXXXXX \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions
```

## Tips

- Name databases by environment (e.g., `staging`, `production`) to simplify credential management.
- `--chroma-database` is an alias that behaves identically.
