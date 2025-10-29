# Vectorize & Dataset Preparation FAQ

### Can we split the corpus so each partition contains roughly 600k rows?
Yes. Use the updated `prepare_datasets.py --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY --directory-size 600000` to create chunked directories, then run `vectorize.py index --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY --partition-dir ... --partition-out-dir ...` to index them one partition at a time.

### Do partition configs need the original `columns` mapping?
No. The sanitized CSVs already use the correct headers, so the generated vectorize configs leave `"columns": {}`.

### How do I switch OpenAI embedding models?
Pass `--embedding-model` to `vectorize.py index`, e.g. `vectorize.py index --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY --embedding-model text-embedding-3-large ...`.

### How do I index against Chroma Cloud instead of local persistence?
Use the HTTP client flags, for example:
```bash
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --client-type http \
  --chroma-server-host api.trychroma.com \
  --chroma-server-port 443 \
  --chroma-server-ssl \
  --chroma-api-token "$CHROMA_TOKEN" \
  --collection ecc-std \
  --partition-dir workdir/prepare_datasets/output \
  --partition-out-dir ./chroma_cloud_runs
```

Prefer the managed Cloud client? Swap in `--client-type cloud` with the same token, and optionally `--chroma-cloud-tenant` / `--chroma-cloud-database` / `--chroma-cloud-host` overrides. The CLI falls back to `CHROMA_*` environment variables when flags are omitted.

### Which environment variables do I need before running the indexer?
- `OPENAI_API_KEY` – API key for OpenAI embeddings (required unless you pass `--openai-api-key`).
- Chroma Cloud / HTTP client settings fall back to the following env vars when CLI flags are omitted:
  - `CHROMA_SERVER_HOST`
  - `CHROMA_SERVER_PORT`
  - `CHROMA_SERVER_SSL` (`true`, `1`, etc.)
  - `CHROMA_API_TOKEN`
  - `CHROMA_TENANT`
  - `CHROMA_DATABASE`
  You can still override each value explicitly through the corresponding CLI flag if preferred.


### Why can it take a long time between the OpenAI embedding response and the “Indexed … batch …” log?
After embeddings return, ChromaDB still has to write vectors to storage and update its HNSW index. As the collection grows, rebuilding those graph layers becomes more expensive, so batches take longer to finish even though the HTTP call already succeeded.

### Why does the indexer pause for a long time after logging `Skipping ClassSignature...` and similar messages?
When resuming, the CLI still streams through any “skipped” CSV rows to reach the first new record. That I/O-only fast‑forward can take a while on large files and happens before any Chroma calls are made.

### Is ChromaDB responsible for that delay?
No. The slowdown occurs before we touch Chroma—it’s purely the CSV reader advancing past the already indexed rows.

### Would storing the file’s byte offset in the resume state help?
Yes. By saving the seek position (plus column headers) we can jump straight to the next unread row and avoid rescanning the whole file on resume.

### After resuming, why didn’t the new `file_offset` field show up in my `_resume_state.json`?
The state file only updates after a successful `upsert`. If the process dies between the OpenAI embedding response and the Chroma write, the flush never happens and the offset isn’t persisted.

### What do the new resume-state fields represent?
- `file_offset` – the byte offset within the CSV where ingestion stopped.
- `row_index` – the last processed row number.
- `fieldnames` – cached CSV header names so the parser can resume mid-file.

### Can I resume an interrupted partition run?
Yes. Every partition keeps its own resume metadata in `<partition-out-dir>/<partition>/collection_resume_state.json`, so subsequent runs skip completed models.

### Does `prepare_datasets.py` validate rows against the Pydantic models?
No. The prepare step focuses on CSV hygiene—fixing headers, delimiters, malformed rows, and partition manifests. Pydantic validation happens later when `vectorize.py index` streams each row through the target `ModelSpec`, so schema errors are reported during indexing.
