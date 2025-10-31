# --client-type

**Why we added this flag:** idxr needs to talk to multiple Chroma deployments—local persistent stores, self-hosted HTTP servers, and Chroma Cloud—so we expose an explicit selector.

## What it does

- Chooses the Chroma client implementation:
  - `persistent` (default) – local duckdb-backed store at `--persist-dir`.
  - `http` – self-hosted HTTP server.
  - `cloud` – Chroma Cloud tenant.
- Determines which additional connectivity flags are required.

## Typical usage

```bash
idxr vectorize index \
  --model "$IDXR_MODEL" \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --client-type cloud \
  --chroma-cloud-tenant tenant_id \
  --chroma-cloud-database db_name \
  --chroma-api-token ck-XXXXXXXX
```

## Tips

- Stick with `persistent` for local development; switch to `cloud` when deploying to managed Chroma.
- The HTTP and Cloud clients share most of the same flags; the `cloud` alias preconfigures headers for you.
