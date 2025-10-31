## Querying Multi-Collection Indexes

When indexing large datasets (millions of records) using the `PartitionCollectionStrategy`, your data is distributed across multiple ChromaDB collections. This document explains how to efficiently query across these collections.

### Architecture Overview

**Why Multiple Collections?**

With 16+ million records, a single collection becomes unwieldy. The `PartitionCollectionStrategy` distributes models across multiple collections such that no collection exceeds the `--directory-size` limit. Each partition gets its own collection.

**The Challenge:**

ChromaDB doesn't support cross-collection queries out of the box. If you want to query specific models (e.g., "Table" and "Field"), you need to:
1. Determine which collections contain those models
2. Query each collection in parallel
3. Merge and rank results by distance

**Our Solution:**

The `AsyncMultiCollectionQueryClient` handles this automatically using:
- A query configuration mapping models to collections
- Async/parallel querying with `asyncio`
- Result merging and ranking by distance scores

---

### Step 1: Generate Query Configuration

After indexing completes, generate a `query_config.json` that maps models to their collections:

```bash
vectorize.py generate-query-config \
  --model "$MODEL_REGISTRY_TARGET" \
  --partition-out-dir build/vector \
  --output query_config.json
```

**What this does:**
- Scans all `*_resume_state.json` files in partition directories
- Extracts model names, collection names, and document counts
- Handles dropped models (collections that no longer exist)
- Creates a mapping for efficient query routing

**Example output:**
```json
{
  "model_to_collections": {
    "Table": {
      "collections": ["partition_00001", "partition_00002", "partition_00005"],
      "total_documents": 245000,
      "partitions": ["partition_00001", "partition_00002", "partition_00005"]
    },
    "Field": {
      "collections": ["partition_00002", "partition_00003"],
      "total_documents": 890000,
      "partitions": ["partition_00002", "partition_00003"]
    }
  },
  "collection_to_models": {
    "partition_00001": ["Table", "Function"],
    "partition_00002": ["Table", "Field", "Domain"]
  },
  "metadata": {
    "total_collections": 10,
    "total_models": 5,
    "generated_at": "2025-10-31T12:00:00",
    "partition_out_dir": "/path/to/build/vector"
  }
}
```

---

### Step 2: Query Using AsyncMultiCollectionQueryClient

#### Basic Setup

```python
import asyncio
import os
from pathlib import Path
from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient

async def query_example():
    # Initialize client
    client = AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",  # or "http"
        cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
        cloud_tenant="your-tenant",
        cloud_database="your-database",
    )

    # Use async context manager
    async with client:
        # Your queries here
        results = await client.query(
            query_texts=["SAP transaction tables"],
            n_results=10,
            models=["Table", "Field"],
        )

        # Process results
        for doc_id, distance in zip(results["ids"][0], results["distances"][0]):
            print(f"{doc_id}: {distance}")

# Run
asyncio.run(query_example())
```

#### Configuration Options

**For Chroma Cloud:**
```python
client = AsyncMultiCollectionQueryClient(
    config_path=Path("query_config.json"),
    client_type="cloud",
    cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
    cloud_tenant="default_tenant",
    cloud_database="default_database",
    cloud_host="api.trychroma.com",
    cloud_port=443,
    cloud_ssl=True,
)
```

**For HTTP Server:**
```python
client = AsyncMultiCollectionQueryClient(
    config_path=Path("query_config.json"),
    client_type="http",
    http_host="localhost",
    http_port=8000,
    http_ssl=False,
    http_headers={"Authorization": "Bearer token"},
)
```

---

### Step 3: Query Patterns

#### Pattern 1: Query Specific Models

Query only collections containing specific models:

```python
results = await client.query(
    query_texts=["What are SAP authorization objects?"],
    n_results=10,
    models=["AuthorizationObject", "Profile"],  # Only these models
    where={"has_sem": True},  # Only docs with semantic content
)
```

**What happens:**
1. Client looks up which collections contain "AuthorizationObject" and "Profile"
2. Queries those collections in parallel using `asyncio.gather()`
3. Merges results and ranks by distance
4. Returns top 10 results across all queried collections

#### Pattern 2: Query All Models

Query across all collections:

```python
results = await client.query(
    query_texts=["financial transactions"],
    n_results=20,
    models=None,  # Query everything
)
```

#### Pattern 3: Complex Metadata Filtering

Use ChromaDB's powerful metadata filters:

```python
results = await client.query(
    query_texts=["customer master data"],
    n_results=15,
    models=["Table", "View"],
    where={
        "$and": [
            {"has_sem": True},
            {"schema_version": {"$in": [2, 3]}},
            {"partition_name": {"$ne": "partition_stale"}},
        ]
    },
)
```

**Available operators:**
- `$eq`, `$ne`: Equality/inequality
- `$gt`, `$gte`, `$lt`, `$lte`: Numeric comparisons
- `$in`, `$nin`: List membership
- `$and`, `$or`: Logical operators

#### Pattern 4: Get Documents by ID or Filter

Retrieve specific documents without semantic search:

```python
# Get by IDs
docs = await client.get(
    ids=["Table:abc123", "Field:def456"],
    models=["Table", "Field"],
)

# Get by filter
docs = await client.get(
    where={"model_name": "Table"},
    limit=100,
    offset=0,
    models=["Table"],
)
```

#### Pattern 5: Count Documents

```python
# Count specific models
table_count = await client.count(models=["Table"])

# Count all documents
total_count = await client.count(models=None)
```

#### Pattern 6: Batch Queries

Query multiple texts at once (efficient):

```python
results = await client.query(
    query_texts=[
        "SAP transaction tables",
        "Authorization objects",
        "Customer master data",
    ],
    n_results=5,
    models=["Table"],
)

# Results organized by query index
for i, query_text in enumerate(query_texts):
    print(f"Query {i}: {query_text}")
    print(f"  Results: {results['ids'][i]}")
```

---

### Step 4: Understanding Results

Query results follow ChromaDB's standard format:

```python
{
    "ids": [["doc1", "doc2", "doc3"]],           # Document IDs per query
    "distances": [[0.12, 0.15, 0.18]],           # Distance scores (lower = better)
    "documents": [["text1", "text2", "text3"]],  # Document texts
    "metadatas": [[{...}, {...}, {...}]],        # Metadata per document
    "embeddings": None,                           # Optional embeddings
}
```

**For multiple query texts:**
```python
{
    "ids": [
        ["query1_doc1", "query1_doc2"],  # Results for query 1
        ["query2_doc1", "query2_doc2"],  # Results for query 2
    ],
    "distances": [
        [0.12, 0.15],
        [0.10, 0.20],
    ],
    ...
}
```

**Metadata fields you can filter on:**
- `model_name`: Name of the model (e.g., "Table", "Field")
- `partition_name`: Partition containing this document
- `schema_version`: Schema version (integer)
- `has_sem`: Whether document has semantic content (boolean)
- `source_path`: Original CSV path
- Plus any custom fields from your models' `keyword_fields`

---

### Performance Considerations

#### 1. **Parallel Execution**

All collection queries run in parallel using `asyncio`:

```python
# Behind the scenes:
tasks = [query_collection(coll) for coll in collections]
results = await asyncio.gather(*tasks)
```

**For 10 collections, this is ~10x faster than sequential queries.**

#### 2. **Collection Caching**

Collections are cached after first retrieval:

```python
# First query: fetches collection
await client.query(models=["Table"], ...)

# Second query: uses cached collection
await client.query(models=["Table"], ...)  # Faster
```

#### 3. **Model Filtering**

Always specify `models` when you know what you need:

```python
# ❌ Slow: queries all 50 collections
await client.query(models=None, ...)

# ✅ Fast: queries only 3 collections containing Table
await client.query(models=["Table"], ...)
```

#### 4. **Result Limit**

Use appropriate `n_results`:

```python
# Queries each collection for 100 results, then merges
await client.query(n_results=100, models=["Table"])

# More efficient if you only need 10
await client.query(n_results=10, models=["Table"])
```

---

### Error Handling

The client handles collection-level errors gracefully:

```python
try:
    results = await client.query(
        query_texts=["test query"],
        n_results=10,
        models=["Table"],
    )
except RuntimeError as exc:
    # All collections failed
    print(f"Query failed: {exc}")
```

**Partial failures are logged but don't stop the query:**

```
ERROR: Query to collection partition_00005 failed: Connection timeout
INFO: Query complete: merged results from 9 collection(s)
```

---

### Best Practices

#### 1. **Generate Query Config Once**

Generate after indexing completes, not before every query:

```bash
# After indexing
vectorize.py generate-query-config \
  --partition-out-dir build/vector \
  --output query_config.json

# Commit to version control or store with your application
```

#### 2. **Use Async Context Manager**

Always use `async with` for automatic cleanup:

```python
async with client:
    await client.query(...)
# Connection closed automatically
```

Or manual:

```python
await client.connect()
try:
    await client.query(...)
finally:
    await client.close()
```

#### 3. **Reuse Client Instances**

Create one client and reuse it:

```python
# ✅ Good
client = AsyncMultiCollectionQueryClient(...)
async with client:
    for query in queries:
        await client.query(query_texts=[query], ...)

# ❌ Bad (creates new connection for each query)
for query in queries:
    client = AsyncMultiCollectionQueryClient(...)
    async with client:
        await client.query(...)
```

#### 4. **Filter Early with Metadata**

Use `where` filters to reduce data transfer:

```python
# ✅ Filter at DB level
await client.query(
    where={"has_sem": True, "schema_version": 3},
    ...
)

# ❌ Filter after retrieving all results
results = await client.query(...)
filtered = [r for r in results if r["metadata"]["has_sem"]]
```

#### 5. **Monitor Query Config Freshness**

Regenerate query config after:
- Adding new partitions
- Dropping models
- Schema updates that create new partitions

```bash
# Check metadata timestamp
cat query_config.json | jq '.metadata.generated_at'
```

---

### Troubleshooting

#### "No collections found for models: ['Table']"

**Cause:** Model not in query config or all collections were dropped.

**Fix:**
1. Regenerate query config
2. Check that model was actually indexed
3. Verify partition directories contain resume state files

#### "Client not connected. Call connect() first."

**Cause:** Forgot to call `await client.connect()` or use context manager.

**Fix:**
```python
# Use context manager
async with client:
    await client.query(...)

# Or manual
await client.connect()
await client.query(...)
await client.close()
```

#### "All collection queries failed"

**Cause:** Network issues, authentication failure, or collections don't exist.

**Fix:**
1. Check ChromaDB connection settings
2. Verify API token is valid
3. Ensure collections exist in ChromaDB
4. Check logs for specific errors

---

### Example: Complete Query Workflow

```python
import asyncio
import os
from pathlib import Path
from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient

async def search_sap_knowledge(user_query: str):
    """Search SAP knowledge base across all indexed models."""

    client = AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
    )

    async with client:
        # Try specific models first
        table_results = await client.query(
            query_texts=[user_query],
            n_results=5,
            models=["Table"],
            where={"has_sem": True},
        )

        # Then broader search if needed
        all_results = await client.query(
            query_texts=[user_query],
            n_results=10,
            models=None,
            where={"has_sem": True},
        )

        # Combine and deduplicate
        seen_ids = set()
        combined = []

        for ids, distances, docs, metas in zip(
            table_results["ids"][0] + all_results["ids"][0],
            table_results["distances"][0] + all_results["distances"][0],
            table_results["documents"][0] + all_results["documents"][0],
            table_results["metadatas"][0] + all_results["metadatas"][0],
        ):
            if ids not in seen_ids:
                seen_ids.add(ids)
                combined.append({
                    "id": ids,
                    "distance": distances,
                    "text": docs,
                    "model": metas.get("model_name"),
                })

        # Sort by distance and return top 10
        combined.sort(key=lambda x: x["distance"])
        return combined[:10]

# Usage
results = asyncio.run(search_sap_knowledge("What is table MARA?"))
for r in results:
    print(f"[{r['model']}] {r['text'][:100]}... (score: {r['distance']:.4f})")
```

---

### See Also

- [DOC.md](DOC.md) - Indexing lifecycle documentation
- [ERROR_HANDLING.md](ERROR_HANDLING.md) - Error handling during indexing
- [examples/query_example.py](examples/query_example.py) - Complete working examples
- ChromaDB Documentation - https://docs.trychroma.com/
