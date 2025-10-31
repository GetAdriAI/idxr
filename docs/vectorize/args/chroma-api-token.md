# --chroma-api-token

**Why we added this flag:** both the HTTP and Cloud Chroma clients require authentication; surfacing the API token keeps credentials out of code.

## What it does

- Supplies the bearer token used for HTTP/Cloud authentication.
- Required whenever `--client-type=http` or `--client-type=cloud` is used (unless the server allows anonymous access).
- Ignored for local persistent runs.

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

- Prefer `export CHROMA_API_TOKEN=...` and pass `--chroma-api-token "$CHROMA_API_TOKEN"` to avoid leaking secrets in shell history.
- Tokens expire; automate rotation and run `idxr vectorize status` after rotations to ensure new jobs still authenticate.
