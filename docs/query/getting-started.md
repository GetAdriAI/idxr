# Getting Started with Query

This guide shows you how to query multi-collection ChromaDB indexes created with idxr.

## Prerequisites

1. **Indexed data**: You must have already indexed data using `idxr vectorize index`
2. **Python environment**: Python 3.9+ with idxr installed
3. **ChromaDB access**: Connection details for ChromaDB (local or cloud)

## Installation

The query client is included with the idxr package:

```bash
pip install idxr
```

## Basic Workflow

### Step 1: Generate Query Config

After indexing completes, generate a query configuration:

```bash
idxr vectorize generate-query-config \
  --partition-out-dir build/vector \
  --output query_config.json \
  --model path/to/model_registry.yaml
```

This scans all `*_resume_state.json` files in your partition directory and creates a mapping of model names to collection names.

**Output** (`query_config.json`):

```json
{
  "metadata": {
    "generated_at": "2025-10-31T10:00:00",
    "total_models": 3,
    "total_collections": 5,
    "collection_prefix": null
  },
  "model_to_collections": {
    "Table": {
      "collections": ["partition_00001", "partition_00002"],
      "total_documents": 450000,
      "partitions": ["partition_00001", "partition_00002"]
    },
    "Field": {
      "collections": ["partition_00002", "partition_00003", "partition_00005"],
      "total_documents": 680000,
      "partitions": ["partition_00002", "partition_00003", "partition_00005"]
    }
  },
  "collection_to_models": {
    "partition_00001": ["Table"],
    "partition_00002": ["Table", "Field"],
    "partition_00003": ["Field"],
    "partition_00005": ["Field"]
  }
}
```

### Step 2: Initialize Query Client

```python
from indexer.vectorize_lib import AsyncMultiCollectionQueryClient
from pathlib import Path
import os
import asyncio

async def main():
    # Initialize client with query config
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",  # or "http" for self-hosted
        cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
    ) as client:
        # Client is ready to query
        pass

asyncio.run(main())
```

### Step 3: Query Your Index

#### Query All Models

Search across all collections when you don't know which model contains the answer:

```python
async with AsyncMultiCollectionQueryClient(
    config_path=Path("query_config.json"),
    client_type="cloud",
    cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
) as client:
    results = await client.query(
        query_texts=["What are SAP authorization objects?"],
        n_results=10,
        models=None,  # Query ALL collections
    )

    # Process results
    for doc_id, distance, metadata in zip(
        results["ids"][0],
        results["distances"][0],
        results["metadatas"][0]
    ):
        model = metadata.get("model_name", "unknown")
        print(f"[{model}] {doc_id} - Distance: {distance:.4f}")
```

#### Query Specific Models

Search only relevant collections when you know the model:

```python
results = await client.query(
    query_texts=["transaction table MARA"],
    n_results=10,
    models=["Table"],  # Only query Table collections
)
```

#### Query with Metadata Filters

Combine model filtering with ChromaDB metadata filters:

```python
results = await client.query(
    query_texts=["customer data"],
    n_results=10,
    where={"has_sem": True},  # Only semantic-enabled records
    models=["Table", "Field"],
)
```

## Complete Example

```python
from indexer.vectorize_lib import AsyncMultiCollectionQueryClient
from pathlib import Path
import os
import asyncio

async def search_sap_index():
    """Complete example: query multi-collection index."""

    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
    ) as client:
        # Example 1: Broad search across all models
        print("=== Searching all models ===")
        results = await client.query(
            query_texts=["SAP authorization"],
            n_results=5,
            models=None,
        )

        for i, (doc_id, distance, metadata) in enumerate(
            zip(
                results["ids"][0],
                results["distances"][0],
                results["metadatas"][0]
            ),
            1
        ):
            model = metadata.get("model_name", "unknown")
            print(f"{i}. [{model}] {doc_id} - Distance: {distance:.4f}")

        # Example 2: Targeted search in Table model
        print("\n=== Searching Table model only ===")
        results = await client.query(
            query_texts=["transaction tables"],
            n_results=5,
            models=["Table"],
        )

        # Example 3: Count total documents
        total = await client.count(models=None)
        print(f"\nTotal documents in index: {total:,}")

if __name__ == "__main__":
    asyncio.run(search_sap_index())
```

## Connection Types

### ChromaDB Cloud

```python
async with AsyncMultiCollectionQueryClient(
    config_path=Path("query_config.json"),
    client_type="cloud",
    cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
) as client:
    pass
```

### Self-Hosted ChromaDB

```python
async with AsyncMultiCollectionQueryClient(
    config_path=Path("query_config.json"),
    client_type="http",
    http_host="localhost:8000",
) as client:
    pass
```

## Next Steps

- Explore [API Reference](api-reference.md) for all available methods
- Check [Examples](examples.md) for advanced query patterns
- Review [Configuration](config.md) for query config options
- Read [Best Practices](best-practices.md) for performance optimization
