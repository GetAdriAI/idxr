# Vectorize

`idxr vectorize` ingests partitions and upserts documents into Chroma. It is designed for long-running, resume-friendly indexing jobs that can target local persistent stores or Chroma Cloud tenants.

## Responsibilities

1. **Model validation** – the same registry used by `prepare_datasets` drives schema-aware indexing and metadata enrichment.
2. **Token budgeting** – dynamic truncation strategies ensure each document respects the embedding model’s token limits.
3. **Resume state** – batch offsets, row digests, and manifest progress are checkpointed so reruns skip already indexed slices.
4. **Observability** – structured logs, optional log rotation, and error YAML payloads make failures debuggable.
5. **Multi-tenant support** – built-in clients for local persistent stores and Chroma Cloud, with pluggable collection strategies.

## Workflow Summary

1. **Generate configs** – either edit a vectorize JSON config manually or let `idxr prepare_datasets` generate partition manifests.
2. **Run `idxr vectorize index`** – point at the manifest or config, choose an output location for per-partition persistence, and supply the required connectivity flags.
3. **Resume as needed** – re-run with `--resume` to pick up where you left off after a failure or partial run.
4. **Inspect progress** – use `idxr vectorize status` to compare manifest entries against indexed partitions and ensure the run completed.

The following pages document configuration schemas and command-line flags in detail.
