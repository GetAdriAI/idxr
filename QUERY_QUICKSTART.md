# Query Quick Start Guide

Quick reference for querying multi-collection ChromaDB indexes.

## Prerequisites

✅ Indexed data using `PartitionCollectionStrategy`
✅ ChromaDB Cloud or HTTP server access
✅ Python 3.8+ with async support

## Step 1: Generate Query Config (One-time)

After indexing completes:

```bash
vectorize.py generate-query-config \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-out-dir build/vector \
  --output query_config.json
```

**Output shows:**
```
================================================================================
Query Configuration Generated
================================================================================
Output File:        query_config.json
Total Models:       5
Total Collections:  12
Generated At:       2025-10-31T12:00:00
================================================================================
```

## Step 2: Install Dependencies

```bash
pip install chromadb asyncio
```

## Step 3: Basic Query

```python
import asyncio
import os
from pathlib import Path
from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient

async def main():
    client = AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
    )

    async with client:
        results = await client.query(
            query_texts=["your search query"],
            n_results=10,
            models=["Table", "Field"],  # or None for all
        )

        for doc_id, distance in zip(results["ids"][0], results["distances"][0]):
            print(f"{doc_id}: {distance:.4f}")

asyncio.run(main())
```

## Common Query Patterns

### Query Specific Models
```python
results = await client.query(
    query_texts=["SAP tables"],
    n_results=10,
    models=["Table", "Field"],
)
```

### Query All Models
```python
results = await client.query(
    query_texts=["authorization"],
    n_results=10,
    models=None,
)
```

### With Metadata Filter
```python
results = await client.query(
    query_texts=["customer data"],
    n_results=10,
    models=["Table"],
    where={"has_sem": True},  # Only semantic content
)
```

### Complex Filter
```python
results = await client.query(
    query_texts=["financial"],
    n_results=10,
    models=["Table", "View"],
    where={
        "$and": [
            {"has_sem": True},
            {"schema_version": {"$in": [2, 3]}},
        ]
    },
)
```

### Get by ID
```python
docs = await client.get(
    ids=["Table:abc123"],
    models=["Table"],
)
```

### Count Documents
```python
count = await client.count(models=["Table"])
print(f"Total Table docs: {count:,}")
```

## Configuration

### For Chroma Cloud
```python
client = AsyncMultiCollectionQueryClient(
    config_path=Path("query_config.json"),
    client_type="cloud",
    cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
    cloud_tenant="your-tenant",
    cloud_database="your-database",
)
```

### For HTTP Server
```python
client = AsyncMultiCollectionQueryClient(
    config_path=Path("query_config.json"),
    client_type="http",
    http_host="localhost",
    http_port=8000,
    http_ssl=False,
)
```

## Result Structure

```python
{
    "ids": [["doc1", "doc2", ...]],          # Per query
    "distances": [[0.12, 0.15, ...]],        # Lower = better match
    "documents": [["text1", "text2", ...]],  # Document texts
    "metadatas": [[{...}, {...}, ...]],      # Metadata dicts
}
```

### Accessing Results
```python
for i, (doc_id, distance, document, metadata) in enumerate(
    zip(
        results["ids"][0],
        results["distances"][0],
        results["documents"][0],
        results["metadatas"][0],
    )
):
    model = metadata.get("model_name")
    partition = metadata.get("partition_name")
    print(f"{i+1}. [{model}] {doc_id} - {distance:.4f}")
```

## Available Metadata Fields

- `model_name` - Model type (e.g., "Table", "Field")
- `partition_name` - Source partition
- `schema_version` - Schema version (int)
- `has_sem` - Has semantic content (bool)
- `source_path` - Original CSV path
- Plus custom fields from your model's `keyword_fields`

## Filter Operators

- **Comparison:** `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`
- **List:** `$in`, `$nin`
- **Logical:** `$and`, `$or`

## Performance Tips

✅ Specify `models` parameter when possible
✅ Use metadata filters to reduce data transfer
✅ Reuse client instances
✅ Use reasonable `n_results` values
✅ Let asyncio handle parallelization

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| "Client not connected" | Forgot to connect | Use `async with client:` |
| "No collections found" | Model not indexed | Check model name, regenerate config |
| "Query config not loaded" | Bad config path | Verify path exists |

## When to Regenerate Config

🔄 After adding new partitions
🔄 After dropping models
🔄 After schema updates creating new partitions
🔄 After re-indexing with different collection strategy

```bash
# Check config timestamp
cat query_config.json | jq '.metadata.generated_at'
```

## Full Documentation

📖 [QUERYING.md](QUERYING.md) - Complete guide
📖 [examples/query_example.py](examples/query_example.py) - Working examples
📖 ChromaDB Docs - https://docs.trychroma.com/

## Quick Test

```python
import asyncio
from pathlib import Path
from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient

async def test():
    client = AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-token",
    )
    async with client:
        count = await client.count(models=None)
        print(f"Total documents: {count:,}")

asyncio.run(test())
```
