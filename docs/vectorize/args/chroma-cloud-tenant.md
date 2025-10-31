# --chroma-cloud-tenant

**Why we added this flag:** Chroma Cloud isolates data per tenant; the tenant header must accompany every API call, so idxr surfaces it explicitly.

## What it does

- Specifies the tenant identifier when `--client-type=cloud`.
- Sets the `X-Chroma-Tenant` header on every request.
- Required for Chroma Cloud runs; ignored for persistent or HTTP clients.

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

- Environment variables keep sensitive values out of shell history: `export CHROMA_TENANT=...` and pass `--chroma-cloud-tenant "$CHROMA_TENANT"`.
- `--chroma-tenant` is an alias; use either name for compatibility with older scripts.
