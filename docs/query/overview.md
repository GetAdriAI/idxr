# Query

The idxr query client provides async query capabilities for multi-collection ChromaDB indexes. When indexing large datasets (16M+ records), idxr distributes data across multiple ChromaDB collections using the `PartitionCollectionStrategy`. The query client enables efficient querying across these partitions with automatic fan-out, result merging, and model-based filtering.

## Responsibilities

1. **Query config generation** – scan indexed partitions to build model-to-collection mappings from resume state files.
2. **Multi-collection fan-out** – automatically distribute queries across relevant collections based on model filters.
3. **Parallel execution** – leverage asyncio to query collections concurrently for optimal performance.
4. **Result merging** – combine and rank results by distance across all queried collections.
5. **Graceful degradation** – handle partial collection failures while returning available results.

## Workflow Summary

1. **Generate query config** – after indexing completes, run `idxr vectorize generate-query-config` to create a query configuration mapping models to collections.
2. **Initialize query client** – use `AsyncMultiCollectionQueryClient` with the generated config to connect to your ChromaDB instance.
3. **Query with model filters** – specify which models to query (or `models=None` for all collections) and let the client handle fan-out and merging.
4. **Retrieve results** – get merged, ranked results from multiple collections as if querying a single collection.

## Key Features

### Model-Based Filtering

Query specific models or all models:

```python
# Query only Table and Field models
results = await client.query(
    query_texts=["SAP transaction tables"],
    models=["Table", "Field"],
)

# Query all models
results = await client.query(
    query_texts=["authorization objects"],
    models=None,
)
```

### Automatic Collection Mapping

The query config automatically maps model names to their collections:

```json
{
  "model_to_collections": {
    "Table": {
      "collections": ["partition_00001", "partition_00003"],
      "total_documents": 450000
    },
    "Field": {
      "collections": ["partition_00002", "partition_00003", "partition_00005"],
      "total_documents": 680000
    }
  }
}
```

### Parallel Query Execution

Queries are executed in parallel using `asyncio.gather()`:

- **Performance**: Latency bound by slowest collection, not sum of all queries
- **Concurrency**: Collection-level parallelization safe for use with thread pools
- **Resilience**: Partial failures don't block successful collections

### Result Merging

Results from multiple collections are:

1. Collected from all queried collections
2. Sorted by distance score (ascending)
3. Limited to requested `n_results`
4. Returned in standard ChromaDB query format

## Architecture

```
User Query
    ↓
AsyncMultiCollectionQueryClient
    ↓
Query Config (model → collections mapping)
    ↓
Fan-out to Collections (asyncio.gather)
    ↓
    ├─→ partition_00001.query()
    ├─→ partition_00002.query()
    └─→ partition_00003.query()
    ↓
Merge Results (by distance)
    ↓
Return Top N Results
```

## Use Cases

### Broad Search (models=None)

Use when you don't know which model contains the answer:

```python
# User asks: "What is SAP authorization?"
# Could be in Table, Function, AuthObject, or other models
results = await client.query(
    query_texts=["SAP authorization"],
    models=None,  # Search all models
)
```

**Performance**: Queries all collections (e.g., 10 partitions in parallel)

### Targeted Search (specific models)

Use when you know the relevant model(s):

```python
# User asks: "Show me transaction table MARA"
# Definitely in Table model
results = await client.query(
    query_texts=["transaction table MARA"],
    models=["Table"],  # Only search Table collections
)
```

**Performance**: Queries only relevant collections (e.g., 2 partitions in parallel)

## Performance Considerations

| Query Type | Collections Queried | Approx. Latency | Best For |
|------------|-------------------|-----------------|----------|
| `models=None` | All (10 partitions) | ~500ms | Exploratory search, unknown model |
| `models=["Table"]` | Subset (2 partitions) | ~200ms | Targeted search, known model |
| `models=["Table", "Field"]` | Union (5 partitions) | ~350ms | Multi-model search |

**Note**: Latency is bound by the slowest collection due to parallel execution.

## Next Steps

- Read [Getting Started](getting-started.md) for installation and basic usage
- Explore [API Reference](api-reference.md) for detailed client documentation
- Check [Examples](examples.md) for common query patterns
- Review [Configuration](config.md) for query config generation options
