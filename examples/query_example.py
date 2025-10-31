"""Example usage of AsyncMultiCollectionQueryClient for querying across partitions.

This example demonstrates how to:
1. Generate a query_config.json from partition resume states
2. Use AsyncMultiCollectionQueryClient to query across multiple collections
3. Filter queries by model names
4. Query all collections without model filtering
"""

import asyncio
import os
from pathlib import Path

from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient
from indexer.vectorize_lib.query_config import generate_query_config


async def example_query_usage():
    """Example of using the async query client."""

    # Step 1: Generate query config (do this once after indexing completes)
    # In practice, you would run this via CLI:
    # vectorize.py generate-query-config \
    #   --partition-out-dir build/vector \
    #   --output query_config.json

    partition_out_dir = Path("build/vector")
    query_config_path = Path("query_config.json")

    if not query_config_path.exists():
        print("Generating query config...")
        try:
            generate_query_config(
                partition_out_dir=partition_out_dir,
                output_path=query_config_path,
            )
            print(f"Query config generated at {query_config_path}")
        except Exception as exc:
            print(f"Failed to generate query config: {exc}")
            return

    # Step 2: Initialize the async query client
    # For Chroma Cloud
    client = AsyncMultiCollectionQueryClient(
        config_path=query_config_path,
        client_type="cloud",
        cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
        cloud_tenant=os.getenv("CHROMA_TENANT", "default_tenant"),
        cloud_database=os.getenv("CHROMA_DATABASE", "default_database"),
    )

    # Or for HTTP client:
    # client = AsyncMultiCollectionQueryClient(
    #     config_path=query_config_path,
    #     client_type="http",
    #     http_host="localhost",
    #     http_port=8000,
    #     http_ssl=False,
    # )

    # Step 3: Use the client with async context manager
    async with client:
        print("\n" + "=" * 80)
        print("Example 1: Query specific models (Table and Field)")
        print("=" * 80)

        # Query only Table and Field models
        results = await client.query(
            query_texts=["What are the main SAP transaction tables?"],
            n_results=5,
            models=["Table", "Field"],  # Only query these models
            where={"has_sem": True},  # Only documents with semantic content
        )

        print(f"\nFound {len(results['ids'][0])} results from Table and Field models:")
        for i, (doc_id, distance, metadata) in enumerate(
            zip(results["ids"][0], results["distances"][0], results["metadatas"][0]), 1
        ):
            model = metadata.get("model_name", "unknown")
            partition = metadata.get("partition_name", "unknown")
            print(f"  {i}. [{model}] ID: {doc_id[:50]}... (distance: {distance:.4f})")
            print(f"     Partition: {partition}")

        print("\n" + "=" * 80)
        print("Example 2: Query all models")
        print("=" * 80)

        # Query all collections (no model filter)
        results = await client.query(
            query_texts=["SAP authorization objects"],
            n_results=3,
            models=None,  # Query all models
        )

        print(f"\nFound {len(results['ids'][0])} results across all models:")
        for i, (_doc_id, doc_text, distance, metadata) in enumerate(
            zip(
                results["ids"][0],
                results["documents"][0],
                results["distances"][0],
                results["metadatas"][0],
            ),
            1,
        ):
            model = metadata.get("model_name", "unknown")
            print(f"  {i}. [{model}] Distance: {distance:.4f}")
            print(f"     Text preview: {doc_text[:100]}...")

        print("\n" + "=" * 80)
        print("Example 3: Get documents by metadata filter")
        print("=" * 80)

        # Get documents by metadata
        docs = await client.get(
            where={
                "$and": [
                    {"model_name": "Table"},
                    {"has_sem": True},
                ]
            },
            limit=5,
            models=["Table"],
        )

        print(f"\nRetrieved {len(docs['ids'])} Table documents with semantic content:")
        for i, (doc_id, metadata) in enumerate(zip(docs["ids"], docs["metadatas"]), 1):
            partition = metadata.get("partition_name", "unknown")
            print(f"  {i}. {doc_id[:60]}... (partition: {partition})")

        print("\n" + "=" * 80)
        print("Example 4: Count documents")
        print("=" * 80)

        # Count documents for specific models
        table_count = await client.count(models=["Table"])
        print(f"Total Table documents: {table_count:,}")

        # Count all documents
        total_count = await client.count(models=None)
        print(f"Total documents across all models: {total_count:,}")

        print("\n" + "=" * 80)
        print("Example 5: Query with complex filters")
        print("=" * 80)

        # Complex query with metadata filters
        results = await client.query(
            query_texts=["financial transactions"],
            n_results=5,
            models=["Table", "Function"],
            where={
                "$and": [
                    {"has_sem": True},
                    {"schema_version": 1},  # Specific schema version
                ]
            },
        )

        print(f"\nFound {len(results['ids'][0])} results with filters:")
        for i, (_doc_id, distance, metadata) in enumerate(
            zip(results["ids"][0], results["distances"][0], results["metadatas"][0]), 1
        ):
            model = metadata.get("model_name", "unknown")
            schema_ver = metadata.get("schema_version", "N/A")
            print(f"  {i}. [{model}] Schema v{schema_ver} - Distance: {distance:.4f}")


async def example_batch_queries():
    """Example of running multiple queries in parallel."""
    query_config_path = Path("query_config.json")

    if not query_config_path.exists():
        print("Query config not found. Run example_query_usage() first.")
        return

    client = AsyncMultiCollectionQueryClient(
        config_path=query_config_path,
        client_type="cloud",
        cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
    )

    async with client:
        print("\n" + "=" * 80)
        print("Example: Batch queries (multiple query texts)")
        print("=" * 80)

        # Query with multiple query texts at once
        query_texts = [
            "SAP transaction tables",
            "Authorization objects",
            "Customer master data",
        ]

        results = await client.query(
            query_texts=query_texts,
            n_results=3,
            models=["Table"],
        )

        # Results are organized by query index
        for query_idx, query_text in enumerate(query_texts):
            print(f"\nQuery {query_idx + 1}: '{query_text}'")
            print(f"  Found {len(results['ids'][query_idx])} results:")
            for doc_id, distance in zip(
                results["ids"][query_idx],
                results["distances"][query_idx],
            ):
                print(f"    - {doc_id[:50]}... (distance: {distance:.4f})")


def main():
    """Run the examples."""
    print("=" * 80)
    print("Async Multi-Collection Query Client Examples")
    print("=" * 80)
    print("\nMake sure you have:")
    print("1. Indexed your data using partition mode")
    print("2. Set CHROMA_API_TOKEN environment variable (for cloud)")
    print("3. Generated query_config.json or have partition output directory")
    print("=" * 80)

    # Run examples
    asyncio.run(example_query_usage())

    print("\n\n")

    # Run batch example
    asyncio.run(example_batch_queries())


if __name__ == "__main__":
    main()
