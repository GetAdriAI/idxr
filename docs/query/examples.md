# Query Examples

Practical examples for common query patterns with AsyncMultiCollectionQueryClient.

## Basic Queries

### Query All Models

Search across all collections when you don't know which model contains the answer:

```python
from indexer.vectorize_lib import AsyncMultiCollectionQueryClient
from pathlib import Path
import asyncio

async def query_all():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        results = await client.query(
            query_texts=["What are SAP authorization objects?"],
            n_results=10,
            models=None,  # Query ALL collections
        )

        print(f"Found {len(results['ids'][0])} results:")
        for doc_id, distance, metadata in zip(
            results["ids"][0],
            results["distances"][0],
            results["metadatas"][0]
        ):
            model = metadata.get("model_name", "unknown")
            print(f"  [{model}] {doc_id} - Distance: {distance:.4f}")

asyncio.run(query_all())
```

### Query Specific Models

Search only relevant collections when you know the model:

```python
async def query_specific():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        results = await client.query(
            query_texts=["transaction table MARA"],
            n_results=10,
            models=["Table"],  # Only Table collections
        )

        for doc_id in results["ids"][0]:
            print(f"  {doc_id}")

asyncio.run(query_specific())
```

## Advanced Filtering

### Query with Metadata Filters

Combine model filtering with metadata constraints:

```python
async def query_with_filters():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        # Only semantic-enabled records
        results = await client.query(
            query_texts=["customer data"],
            n_results=10,
            where={"has_sem": True},
            models=["Table", "Field"],
        )

        # Complex filter
        results = await client.query(
            query_texts=["sales data"],
            n_results=10,
            where={
                "$and": [
                    {"has_sem": True},
                    {"schema_version": {"$gte": 2}},
                    {"model_name": {"$in": ["Table", "View"]}}
                ]
            },
            models=None,
        )

asyncio.run(query_with_filters())
```

## Batch Queries

### Query Multiple Texts in Parallel

Query multiple search terms simultaneously:

```python
async def batch_query():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        # Query 3 different texts at once
        results = await client.query(
            query_texts=[
                "SAP authorization objects",
                "transaction tables",
                "customer master data"
            ],
            n_results=5,
            models=None,
        )

        # Process results for each query
        for query_idx, query_text in enumerate([
            "SAP authorization objects",
            "transaction tables",
            "customer master data"
        ]):
            print(f"\nResults for: {query_text}")
            for doc_id, distance in zip(
                results["ids"][query_idx],
                results["distances"][query_idx]
            ):
                print(f"  {doc_id} - {distance:.4f}")

asyncio.run(batch_query())
```

## Document Retrieval

### Get Documents by ID

Retrieve specific documents from collections:

```python
async def get_by_id():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        docs = await client.get(
            ids=["Table_MARA_001", "Field_MATNR_001"],
            models=["Table", "Field"],
        )

        for doc_id, doc_text, metadata in zip(
            docs["ids"],
            docs["documents"],
            docs["metadatas"]
        ):
            print(f"{doc_id}:")
            print(f"  Text: {doc_text[:100]}...")
            print(f"  Metadata: {metadata}")

asyncio.run(get_by_id())
```

### Get Documents with Filter

Retrieve documents matching criteria:

```python
async def get_with_filter():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        docs = await client.get(
            where={
                "has_sem": True,
                "model_name": "Table"
            },
            limit=100,
            models=None,
        )

        print(f"Retrieved {len(docs['ids'])} documents")

asyncio.run(get_with_filter())
```

## Counting

### Count Documents

Get document counts across collections:

```python
async def count_documents():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        # Count all documents
        total = await client.count(models=None)
        print(f"Total documents: {total:,}")

        # Count by model
        table_count = await client.count(models=["Table"])
        print(f"Table documents: {table_count:,}")

        # Count with filter
        sem_count = await client.count(
            where={"has_sem": True},
            models=None,
        )
        print(f"Semantic-enabled documents: {sem_count:,}")

asyncio.run(count_documents())
```

## RAG Pipeline Integration

### Semantic Search for RAG

Integrate with RAG (Retrieval-Augmented Generation) pipeline:

```python
import openai
from indexer.vectorize_lib import AsyncMultiCollectionQueryClient
from pathlib import Path

async def rag_search(user_question: str) -> str:
    """Search index and generate answer using RAG."""

    # Step 1: Retrieve relevant documents
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        results = await client.query(
            query_texts=[user_question],
            n_results=5,
            models=None,
        )

    # Step 2: Extract context from results
    context_docs = []
    for doc_text, metadata in zip(
        results["documents"][0],
        results["metadatas"][0]
    ):
        model = metadata.get("model_name", "unknown")
        context_docs.append(f"[{model}] {doc_text}")

    context = "\n\n".join(context_docs)

    # Step 3: Generate answer with LLM
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {
                "role": "system",
                "content": "Answer questions based on the provided context."
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {user_question}"
            }
        ]
    )

    return response.choices[0].message.content

# Usage
answer = asyncio.run(rag_search("What are SAP authorization objects?"))
print(answer)
```

## Error Handling

### Graceful Degradation

Handle partial collection failures:

```python
async def robust_query():
    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        try:
            results = await client.query(
                query_texts=["search term"],
                n_results=10,
                models=None,
            )

            # Check if we got results
            if len(results["ids"][0]) == 0:
                print("No results found")
            else:
                print(f"Found {len(results['ids'][0])} results")

        except RuntimeError as e:
            print(f"Client error: {e}")
        except ValueError as e:
            print(f"Invalid query: {e}")

asyncio.run(robust_query())
```

## Performance Optimization

### Model-Specific Queries

Optimize performance by querying only relevant models:

```python
async def optimized_query(query_text: str, intent: str):
    """Route queries to relevant models based on intent."""

    # Map intents to models
    intent_to_models = {
        "table_lookup": ["Table"],
        "field_search": ["Field"],
        "authorization": ["AuthObject", "Function"],
        "general": None,  # Query all
    }

    models = intent_to_models.get(intent, None)

    async with AsyncMultiCollectionQueryClient(
        config_path=Path("query_config.json"),
        client_type="cloud",
        cloud_api_key="your-api-key",
    ) as client:
        results = await client.query(
            query_texts=[query_text],
            n_results=10,
            models=models,
        )

        return results

# Fast lookup in Table model only
results = asyncio.run(optimized_query("MARA table", "table_lookup"))

# Broad search across all models
results = asyncio.run(optimized_query("SAP authorization", "general"))
```

## Complete Application Example

### Full-Featured Search Application

```python
from indexer.vectorize_lib import (
    AsyncMultiCollectionQueryClient,
    generate_query_config,
)
from pathlib import Path
import os
import asyncio
from typing import Optional, List

class SAPIndexSearch:
    """Wrapper for SAP index search functionality."""

    def __init__(self, config_path: Path, api_key: str):
        self.config_path = config_path
        self.api_key = api_key
        self.client: Optional[AsyncMultiCollectionQueryClient] = None

    async def __aenter__(self):
        self.client = AsyncMultiCollectionQueryClient(
            config_path=self.config_path,
            client_type="cloud",
            cloud_api_key=self.api_key,
        )
        await self.client.connect()
        return self

    async def __aexit__(self, *args):
        if self.client:
            await self.client.close()

    async def search(
        self,
        query: str,
        models: Optional[List[str]] = None,
        filters: Optional[dict] = None,
        limit: int = 10
    ) -> List[dict]:
        """Search with automatic model routing."""
        results = await self.client.query(
            query_texts=[query],
            n_results=limit,
            where=filters,
            models=models,
        )

        # Format results
        formatted = []
        for doc_id, distance, doc_text, metadata in zip(
            results["ids"][0],
            results["distances"][0],
            results["documents"][0],
            results["metadatas"][0]
        ):
            formatted.append({
                "id": doc_id,
                "score": 1 - distance,  # Convert to similarity
                "text": doc_text,
                "model": metadata.get("model_name"),
                "metadata": metadata,
            })

        return formatted

    async def get_stats(self) -> dict:
        """Get index statistics."""
        total = await self.client.count(models=None)

        # Count per model (example with known models)
        models = ["Table", "Field", "Function"]
        model_counts = {}
        for model in models:
            try:
                count = await self.client.count(models=[model])
                model_counts[model] = count
            except:
                pass

        return {
            "total_documents": total,
            "model_counts": model_counts,
        }

# Usage
async def main():
    async with SAPIndexSearch(
        config_path=Path("query_config.json"),
        api_key=os.getenv("CHROMA_API_TOKEN"),
    ) as search:
        # Search
        results = search.await search(
            "SAP authorization objects",
            models=None,
            limit=5
        )

        for result in results:
            print(f"[{result['model']}] Score: {result['score']:.4f}")
            print(f"  {result['text'][:100]}...")

        # Stats
        stats = await search.get_stats()
        print(f"\nIndex Statistics:")
        print(f"  Total: {stats['total_documents']:,}")
        for model, count in stats['model_counts'].items():
            print(f"  {model}: {count:,}")

asyncio.run(main())
```

## Next Steps

- Review [API Reference](api-reference.md) for complete method documentation
- Check [Best Practices](best-practices.md) for performance tips
- Read [Configuration](config.md) for query config options
