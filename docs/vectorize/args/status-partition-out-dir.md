# status --partition-out-dir

**Why we added this flag:** the status subcommand inspects actual index outputs; it needs to know where `idxr vectorize index` wrote its per-partition artifacts.

## What it does

- Points `idxr vectorize status` at the root directory that contains partition-specific resume files and chunk metadata.
- Required for the status command.
- Used to determine which partitions are complete, in progress, or missing.

## Typical usage

```bash
idxr vectorize status \
  --model "$IDXR_MODEL" \
  --partition-out-dir workdir/chroma_partitions
```

## Tips

- Run status immediately after indexing; it highlights partitions that never started or were interrupted mid-run.
- Store this directory on persistent storage so status remains accurate after restarts.
