"""Async query client for multi-collection ChromaDB queries with fan-out support."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import chromadb
from chromadb import AsyncClientAPI
from chromadb.api.types import (
    EmbeddingFunction,
    Include,
    QueryResult,
    WhereDocument,
)

from .query_config import get_collections_for_models, load_query_config

logger = logging.getLogger(__name__)


class AsyncMultiCollectionQueryClient:
    """Async query client that fans out queries across multiple ChromaDB collections.

    This client wraps ChromaDB's async API to enable efficient querying across
    multiple collections (partitions) by model name. It uses asyncio to query
    collections in parallel and merge results by distance scores.

    Example:
        >>> config_path = Path("query_config.json")
        >>> client = AsyncMultiCollectionQueryClient(
        ...     config_path=config_path,
        ...     client_type="cloud",
        ...     cloud_api_key="...",
        ... )
        >>> await client.connect()
        >>> results = await client.query(
        ...     query_texts=["SAP table structures"],
        ...     n_results=10,
        ...     models=["Table", "Field"],
        ... )
        >>> await client.close()
    """

    def __init__(
        self,
        config_path: Path,
        *,
        client_type: str = "http",
        http_host: Optional[str] = None,
        http_port: Optional[int] = None,
        http_ssl: bool = False,
        http_headers: Optional[Mapping[str, str]] = None,
        cloud_api_key: Optional[str] = None,
        cloud_tenant: Optional[str] = "default_tenant",
        cloud_database: Optional[str] = "default_database",
        cloud_host: str = "api.trychroma.com",
        cloud_port: int = 443,
        cloud_ssl: bool = True,
        embedding_function: Optional[EmbeddingFunction[Any]] = None,
    ):
        """Initialize the async query client.

        Args:
            config_path: Path to query_config.json file
            client_type: Type of ChromaDB client ("http" or "cloud")
            http_host: Host for HTTP client
            http_port: Port for HTTP client
            http_ssl: Use SSL for HTTP client
            http_headers: Headers for HTTP client
            cloud_api_key: API key for Chroma Cloud
            cloud_tenant: Tenant ID for Chroma Cloud
            cloud_database: Database name for Chroma Cloud
            cloud_host: Host for Chroma Cloud
            cloud_port: Port for Chroma Cloud
            cloud_ssl: Use SSL for Chroma Cloud
            embedding_function: Optional embedding function for queries
        """
        self.config_path = config_path
        self.client_type = client_type
        self.embedding_function = embedding_function

        # HTTP client settings
        self.http_host = http_host
        self.http_port = http_port or 8000
        self.http_ssl = http_ssl
        self.http_headers = dict(http_headers) if http_headers else {}

        # Cloud client settings
        self.cloud_api_key = cloud_api_key
        self.cloud_tenant = cloud_tenant
        self.cloud_database = cloud_database
        self.cloud_host = cloud_host
        self.cloud_port = cloud_port
        self.cloud_ssl = cloud_ssl

        # Runtime state
        self._client: Optional[AsyncClientAPI] = None
        self._query_config: Optional[Dict[str, Any]] = None
        self._collection_cache: Dict[str, Any] = {}

    async def connect(self) -> None:
        """Establish connection to ChromaDB and load query config."""
        # Load query config
        self._query_config = load_query_config(self.config_path)
        logger.info(
            "Loaded query config with %d models and %d collections",
            self._query_config["metadata"]["total_models"],
            self._query_config["metadata"]["total_collections"],
        )

        # Initialize ChromaDB async client
        if self.client_type == "cloud":
            if not self.cloud_api_key:
                raise ValueError("cloud_api_key is required for cloud client type")

            self._client = await chromadb.AsyncCloudClient(  # type: ignore[attr-defined]
                tenant=self.cloud_tenant,
                database=self.cloud_database,
                api_key=self.cloud_api_key,
                host=self.cloud_host,
                port=self.cloud_port,
                ssl=self.cloud_ssl,
            )
            logger.info(
                "Connected to Chroma Cloud (tenant=%s, database=%s)",
                self.cloud_tenant,
                self.cloud_database,
            )
        elif self.client_type == "http":
            if not self.http_host:
                raise ValueError("http_host is required for http client type")

            self._client = await chromadb.AsyncHttpClient(
                host=self.http_host,
                port=self.http_port,
                ssl=self.http_ssl,
                headers=self.http_headers,
            )
            logger.info(
                "Connected to ChromaDB HTTP server at %s://%s:%d",
                "https" if self.http_ssl else "http",
                self.http_host,
                self.http_port,
            )
        else:
            raise ValueError(
                f"Unsupported client_type: {self.client_type}. "
                "Use 'http' or 'cloud'."
            )

    async def close(self) -> None:
        """Close the ChromaDB connection."""
        if self._client is not None:
            # Clear collection cache
            self._collection_cache.clear()
            # Note: AsyncClientAPI doesn't have an explicit close method
            # but we can clear the reference
            self._client = None
            logger.info("Closed ChromaDB connection")

    async def _get_collection(self, collection_name: str) -> Any:
        """Get or retrieve a collection from cache.

        Args:
            collection_name: Name of the collection

        Returns:
            ChromaDB collection object
        """
        if self._client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        if collection_name in self._collection_cache:
            return self._collection_cache[collection_name]

        try:
            collection = await self._client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function,
            )
            self._collection_cache[collection_name] = collection
            return collection
        except Exception as exc:
            logger.error("Failed to get collection %s: %s", collection_name, exc)
            raise

    async def _query_single_collection(
        self,
        collection_name: str,
        *,
        query_embeddings: Optional[Sequence[Sequence[float]]] = None,
        query_texts: Optional[Sequence[str]] = None,
        n_results: int = 10,
        where: Optional[Mapping[str, Any]] = None,
        where_document: Optional[WhereDocument] = None,
        include: Optional[Include] = None,
    ) -> QueryResult:
        """Query a single collection.

        Args:
            collection_name: Name of the collection to query
            query_embeddings: Optional embeddings for the query
            query_texts: Optional text queries (will be embedded)
            n_results: Number of results per query
            where: Metadata filters
            where_document: Document content filters
            include: What to include in results

        Returns:
            Query results from this collection
        """
        collection = await self._get_collection(collection_name)

        try:
            # Set default include if not provided
            if include is None:
                include = ["metadatas", "documents", "distances"]

            result = await collection.query(
                query_embeddings=query_embeddings,
                query_texts=query_texts,
                n_results=n_results,
                where=where,
                where_document=where_document,
                include=include,
            )
            return result
        except Exception as exc:
            logger.error("Failed to query collection %s: %s", collection_name, exc)
            raise

    def _merge_query_results(
        self,
        results: List[QueryResult],
        n_results: int,
        num_queries: int,
    ) -> QueryResult:
        """Merge results from multiple collections by distance.

        Args:
            results: List of QueryResult objects from different collections
            n_results: Maximum number of results to return per query
            num_queries: Number of queries that were executed

        Returns:
            Merged QueryResult with top n_results per query
        """
        # Initialize merged result structure
        merged: Dict[str, Any] = {
            "ids": [[] for _ in range(num_queries)],
            "embeddings": None,
            "documents": [[] for _ in range(num_queries)],
            "metadatas": [[] for _ in range(num_queries)],
            "distances": [[] for _ in range(num_queries)],
            "uris": None,
            "data": None,
            "included": ["embeddings", "documents", "metadatas", "distances"],
        }

        # Collect all results per query index
        for query_idx in range(num_queries):
            query_results: list[tuple] = []

            for result in results:
                if not result or not result.get("ids"):
                    continue

                ids = result["ids"][query_idx] if query_idx < len(result["ids"]) else []

                # Handle distances with proper type checking
                result_distances = result.get("distances")
                if result_distances is not None and query_idx < len(result_distances):
                    distances = result_distances[query_idx]
                else:
                    distances = [float("inf")] * len(ids)

                # Handle documents with proper type checking
                result_documents = result.get("documents")
                if result_documents is not None and query_idx < len(result_documents):
                    documents = result_documents[query_idx]
                else:
                    documents = [""] * len(ids)  # type: ignore[assignment]

                # Handle metadatas with proper type checking
                result_metadatas = result.get("metadatas")
                if result_metadatas is not None and query_idx < len(result_metadatas):
                    metadatas = result_metadatas[query_idx]
                else:
                    metadatas = [{}] * len(ids)  # type: ignore[assignment]

                # Combine into tuples for sorting
                for i in range(len(ids)):
                    query_results.append(
                        (
                            distances[i],
                            ids[i],
                            documents[i],
                            metadatas[i],
                        )
                    )

            # Sort by distance and take top n_results
            query_results.sort(key=lambda x: x[0])
            top_results = query_results[:n_results]

            # Unpack into merged structure
            if top_results:
                merged["distances"][query_idx] = [r[0] for r in top_results]
                merged["ids"][query_idx] = [r[1] for r in top_results]
                merged["documents"][query_idx] = [r[2] for r in top_results]
                merged["metadatas"][query_idx] = [r[3] for r in top_results]

        return merged  # type: ignore[return-value]

    async def query(
        self,
        *,
        query_embeddings: Optional[Sequence[Sequence[float]]] = None,
        query_texts: Optional[Sequence[str]] = None,
        n_results: int = 10,
        where: Optional[Mapping[str, Any]] = None,
        where_document: Optional[WhereDocument] = None,
        include: Optional[Include] = None,
        models: Optional[Sequence[str]] = None,
    ) -> QueryResult:
        """Query across multiple collections with fan-out.

        Args:
            query_embeddings: Optional embeddings for the query
            query_texts: Optional text queries (will be embedded)
            n_results: Number of results to return per query
            where: Metadata filters to apply
            where_document: Document content filters
            include: What to include in results
            models: List of model names to query, or None for all collections

        Returns:
            Merged query results from all relevant collections

        Note:
            - If models is None, queries all collections
            - Results are merged and ranked by distance across collections
            - Queries are executed in parallel using asyncio
        """
        if self._client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        if self._query_config is None:
            raise RuntimeError("Query config not loaded")

        if query_embeddings is None and query_texts is None:
            raise ValueError("Either query_embeddings or query_texts must be provided")

        # Set default include if not provided
        if include is None:
            include = ["metadatas", "documents", "distances"]

        # Determine which collections to query
        model_list = list(models) if models else None
        collections = get_collections_for_models(self._query_config, model_list)

        if not collections:
            logger.warning("No collections found for models: %s", models)
            # Return empty result
            num_queries = len(query_embeddings or query_texts or [])
            empty_result: Dict[str, Any] = {
                "ids": [[] for _ in range(num_queries)],
                "embeddings": None,
                "documents": [[] for _ in range(num_queries)],
                "metadatas": [[] for _ in range(num_queries)],
                "distances": [[] for _ in range(num_queries)],
                "uris": None,
                "data": None,
                "included": include,
            }
            return empty_result  # type: ignore[return-value]

        logger.info(
            "Querying %d collection(s) for models %s",
            len(collections),
            models or "all",
        )

        # Execute queries in parallel
        tasks = [
            self._query_single_collection(
                collection_name=coll,
                query_embeddings=query_embeddings,
                query_texts=query_texts,
                n_results=n_results,
                where=where,
                where_document=where_document,
                include=include,
            )
            for coll in collections
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and log errors
        valid_results: list[QueryResult] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error(
                    "Query to collection %s failed: %s",
                    collections[i],
                    result,
                )
            else:
                valid_results.append(result)  # type: ignore[arg-type]

        if not valid_results:
            raise RuntimeError("All collection queries failed")

        # Merge results from all collections
        num_queries = len(query_embeddings or query_texts or [])
        merged_result = self._merge_query_results(valid_results, n_results, num_queries)

        logger.info(
            "Query complete: merged results from %d collection(s)",
            len(valid_results),
        )

        return merged_result

    async def get(
        self,
        *,
        ids: Optional[Sequence[str]] = None,
        where: Optional[Mapping[str, Any]] = None,
        where_document: Optional[WhereDocument] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Optional[Include] = None,
        models: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Get documents from collections by ID or filter.

        Args:
            ids: Optional list of document IDs to retrieve
            where: Metadata filters
            where_document: Document content filters
            limit: Maximum number of results to return
            offset: Offset for pagination
            include: What to include in results
            models: List of model names to query, or None for all collections

        Returns:
            Dictionary with combined results from all collections
        """
        if self._client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        if self._query_config is None:
            raise RuntimeError("Query config not loaded")

        # Set default include if not provided
        if include is None:
            include = ["metadatas", "documents"]

        # Determine which collections to query
        model_list = list(models) if models else None
        collections = get_collections_for_models(self._query_config, model_list)

        if not collections:
            logger.warning("No collections found for models: %s", models)
            return {
                "ids": [],
                "embeddings": None,
                "documents": [],
                "metadatas": [],
                "uris": None,
                "data": None,
            }

        logger.info(
            "Getting documents from %d collection(s) for models %s",
            len(collections),
            models or "all",
        )

        async def _get_from_collection(collection_name: str) -> Dict[str, Any]:
            collection = await self._get_collection(collection_name)
            return await collection.get(
                ids=ids,
                where=where,
                where_document=where_document,
                limit=limit,
                offset=offset,
                include=include,
            )

        # Execute get operations in parallel
        tasks = [_get_from_collection(coll) for coll in collections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        merged: Dict[str, Any] = {
            "ids": [],
            "embeddings": [],
            "documents": [],
            "metadatas": [],
            "uris": None,
            "data": None,
        }

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error(
                    "Get from collection %s failed: %s",
                    collections[i],
                    result,
                )
                continue

            if result and isinstance(result, dict):
                merged["ids"].extend(result.get("ids", []))
                if result.get("embeddings"):
                    if merged["embeddings"] is None:
                        merged["embeddings"] = []
                    merged["embeddings"].extend(result["embeddings"])
                if result.get("documents"):
                    merged["documents"].extend(result["documents"])
                if result.get("metadatas"):
                    merged["metadatas"].extend(result["metadatas"])

        logger.info(
            "Get complete: retrieved %d document(s) from %d collection(s)",
            len(merged["ids"]),
            len(collections),
        )

        return merged

    async def count(
        self,
        *,
        models: Optional[Sequence[str]] = None,
    ) -> int:
        """Count total documents across collections.

        Args:
            models: List of model names to count, or None for all collections

        Returns:
            Total document count across all relevant collections
        """
        if self._client is None:
            raise RuntimeError("Client not connected. Call connect() first.")

        if self._query_config is None:
            raise RuntimeError("Query config not loaded")

        # Determine which collections to query
        model_list = list(models) if models else None
        collections = get_collections_for_models(self._query_config, model_list)

        if not collections:
            return 0

        async def _count_collection(collection_name: str) -> int:
            collection = await self._get_collection(collection_name)
            return await collection.count()

        # Execute count operations in parallel
        tasks = [_count_collection(coll) for coll in collections]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total = 0
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error(
                    "Count from collection %s failed: %s",
                    collections[i],
                    result,
                )
            elif isinstance(result, int):
                total += result

        return total

    async def __aenter__(self) -> AsyncMultiCollectionQueryClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
