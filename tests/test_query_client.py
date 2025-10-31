"""Tests for AsyncMultiCollectionQueryClient using ChromaDB in-memory client."""

import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient


@pytest.fixture
def query_config_data():
    """Sample query config data."""
    return {
        "model_to_collections": {
            "Table": {
                "collections": ["partition_00001", "partition_00002"],
                "total_documents": 1500,
                "partitions": ["partition_00001", "partition_00002"],
            },
            "Field": {
                "collections": ["partition_00002", "partition_00003"],
                "total_documents": 1100,
                "partitions": ["partition_00002", "partition_00003"],
            },
            "Domain": {
                "collections": ["partition_00003"],
                "total_documents": 300,
                "partitions": ["partition_00003"],
            },
        },
        "collection_to_models": {
            "partition_00001": ["Table"],
            "partition_00002": ["Table", "Field"],
            "partition_00003": ["Field", "Domain"],
        },
        "metadata": {
            "total_collections": 3,
            "total_models": 3,
            "generated_at": "2025-10-31T12:00:00",
        },
    }


@pytest.fixture
def query_config_file(query_config_data):
    """Create a temporary query config file."""
    with TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "query_config.json"
        config_path.write_text(json.dumps(query_config_data), encoding="utf-8")
        yield config_path


@pytest.fixture
def mock_chroma_client():
    """Create a mock ChromaDB async client."""
    client = AsyncMock()

    # Mock collections
    mock_collections = {}

    async def get_collection_side_effect(name, embedding_function=None):
        if name not in mock_collections:
            collection = AsyncMock()
            collection.name = name

            # Mock query results
            async def query_side_effect(
                query_embeddings=None,
                query_texts=None,
                n_results=10,
                where=None,
                where_document=None,
                include=None,
            ):
                num_queries = len(query_embeddings or query_texts or [])
                return {
                    "ids": [
                        [f"{name}_doc_{i}" for i in range(min(n_results, 5))]
                        for _ in range(num_queries)
                    ],
                    "distances": [
                        [0.1 * i for i in range(min(n_results, 5))]
                        for _ in range(num_queries)
                    ],
                    "documents": [
                        [f"Document {i} from {name}" for i in range(min(n_results, 5))]
                        for _ in range(num_queries)
                    ],
                    "metadatas": [
                        [
                            {"model_name": "Table", "partition_name": name}
                            for i in range(min(n_results, 5))
                        ]
                        for _ in range(num_queries)
                    ],
                    "embeddings": None,
                    "uris": None,
                    "data": None,
                }

            collection.query = AsyncMock(side_effect=query_side_effect)

            # Mock get results
            async def get_side_effect(
                ids=None,
                where=None,
                where_document=None,
                limit=None,
                offset=None,
                include=None,
            ):
                return {
                    "ids": [f"{name}_doc_{i}" for i in range(min(limit or 5, 5))],
                    "documents": [
                        f"Document {i} from {name}" for i in range(min(limit or 5, 5))
                    ],
                    "metadatas": [
                        {"model_name": "Table", "partition_name": name}
                        for i in range(min(limit or 5, 5))
                    ],
                    "embeddings": None,
                    "uris": None,
                    "data": None,
                }

            collection.get = AsyncMock(side_effect=get_side_effect)

            # Mock count
            collection.count = AsyncMock(return_value=1000)

            mock_collections[name] = collection

        return mock_collections[name]

    client.get_collection = AsyncMock(side_effect=get_collection_side_effect)

    return client


@pytest.mark.asyncio
async def test_client_initialization(query_config_file):
    """Test client initialization."""
    client = AsyncMultiCollectionQueryClient(
        config_path=query_config_file,
        client_type="http",
        http_host="localhost",
        http_port=8000,
    )

    assert client.config_path == query_config_file
    assert client.client_type == "http"
    assert client.http_host == "localhost"
    assert client.http_port == 8000
    assert client._client is None
    assert client._query_config is None


@pytest.mark.asyncio
async def test_client_connect_loads_config(query_config_file, mock_chroma_client):
    """Test that connect() loads the query config."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        client = AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        )

        await client.connect()

        assert client._query_config is not None
        assert client._query_config["metadata"]["total_models"] == 3
        assert client._query_config["metadata"]["total_collections"] == 3

        await client.close()


@pytest.mark.asyncio
async def test_client_context_manager(query_config_file, mock_chroma_client):
    """Test using client as async context manager."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            assert client._client is not None
            assert client._query_config is not None


@pytest.mark.asyncio
async def test_query_specific_models(query_config_file, mock_chroma_client):
    """Test querying specific models."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            results = await client.query(
                query_texts=["test query"],
                n_results=5,
                models=["Table"],
            )

            # Should query partition_00001 and partition_00002
            assert mock_chroma_client.get_collection.call_count >= 2

            # Check result structure
            assert "ids" in results
            assert "distances" in results
            assert "documents" in results
            assert "metadatas" in results
            assert len(results["ids"]) == 1  # One query
            assert len(results["ids"][0]) <= 5  # Up to 5 results


@pytest.mark.asyncio
async def test_query_all_models(query_config_file, mock_chroma_client):
    """Test querying all models (models=None)."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            results = await client.query(
                query_texts=["test query"],
                n_results=10,
                models=None,  # All collections
            )

            # Should query all 3 collections
            assert mock_chroma_client.get_collection.call_count >= 3

            assert "ids" in results
            assert len(results["ids"]) == 1


@pytest.mark.asyncio
async def test_query_multiple_queries(query_config_file, mock_chroma_client):
    """Test querying with multiple query texts."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            query_texts = ["query 1", "query 2", "query 3"]
            results = await client.query(
                query_texts=query_texts,
                n_results=5,
                models=["Field"],
            )

            # Should have results for each query
            assert len(results["ids"]) == 3
            assert len(results["distances"]) == 3
            assert len(results["documents"]) == 3
            assert len(results["metadatas"]) == 3


@pytest.mark.asyncio
async def test_query_with_metadata_filter(query_config_file, mock_chroma_client):
    """Test querying with metadata filters."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            results = await client.query(
                query_texts=["test"],
                n_results=5,
                models=["Table"],
                where={"has_sem": True},
            )

            assert "ids" in results
            # Verify where parameter was passed to collection.query
            # (would need to check mock call args in more detailed test)


@pytest.mark.asyncio
async def test_query_unknown_model(query_config_file, mock_chroma_client):
    """Test querying unknown model returns empty results."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            results = await client.query(
                query_texts=["test"],
                n_results=5,
                models=["UnknownModel"],
            )

            # Should return empty results
            assert results["ids"] == [[]]
            assert results["distances"] == [[]]


@pytest.mark.asyncio
async def test_query_without_connect_raises(query_config_file):
    """Test that querying without connecting raises error."""
    client = AsyncMultiCollectionQueryClient(
        config_path=query_config_file,
        client_type="http",
        http_host="localhost",
    )

    with pytest.raises(RuntimeError, match="not connected"):
        await client.query(query_texts=["test"], n_results=5)


@pytest.mark.asyncio
async def test_query_without_query_texts_or_embeddings_raises(
    query_config_file, mock_chroma_client
):
    """Test that query without texts or embeddings raises error."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            with pytest.raises(ValueError, match="query_embeddings or query_texts"):
                await client.query(n_results=5)


@pytest.mark.asyncio
async def test_get_documents(query_config_file, mock_chroma_client):
    """Test getting documents by ID or filter."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            docs = await client.get(
                where={"model_name": "Table"},
                limit=10,
                models=["Table"],
            )

            assert "ids" in docs
            assert "documents" in docs
            assert "metadatas" in docs
            assert isinstance(docs["ids"], list)


@pytest.mark.asyncio
async def test_get_unknown_model(query_config_file, mock_chroma_client):
    """Test getting documents for unknown model."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            docs = await client.get(
                models=["UnknownModel"],
                limit=10,
            )

            # Should return empty
            assert docs["ids"] == []


@pytest.mark.asyncio
async def test_count_documents(query_config_file, mock_chroma_client):
    """Test counting documents."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            # Count specific model
            count = await client.count(models=["Table"])
            assert count > 0  # Should be 2000 (1000 per collection)

            # Count all
            total_count = await client.count(models=None)
            assert total_count > 0  # Should be 3000


@pytest.mark.asyncio
async def test_collection_caching(query_config_file, mock_chroma_client):
    """Test that collections are cached after first retrieval."""
    with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            # First query
            await client.query(
                query_texts=["test"],
                n_results=5,
                models=["Table"],
            )

            first_call_count = mock_chroma_client.get_collection.call_count

            # Second query - should use cached collections
            await client.query(
                query_texts=["test 2"],
                n_results=5,
                models=["Table"],
            )

            # Should not have called get_collection again
            assert mock_chroma_client.get_collection.call_count == first_call_count


@pytest.mark.asyncio
async def test_client_initialization_cloud():
    """Test client initialization for cloud."""
    with TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.json"
        config_data = {
            "model_to_collections": {},
            "collection_to_models": {},
            "metadata": {"total_models": 0, "total_collections": 0},
        }
        config_path.write_text(json.dumps(config_data))

        client = AsyncMultiCollectionQueryClient(
            config_path=config_path,
            client_type="cloud",
            cloud_api_key="test_key",
            cloud_tenant="test_tenant",
            cloud_database="test_db",
        )

        assert client.client_type == "cloud"
        assert client.cloud_api_key == "test_key"
        assert client.cloud_tenant == "test_tenant"
        assert client.cloud_database == "test_db"


@pytest.mark.asyncio
async def test_client_http_without_host_raises(query_config_file):
    """Test that HTTP client without host raises error."""
    client = AsyncMultiCollectionQueryClient(
        config_path=query_config_file,
        client_type="http",
        http_host=None,  # Missing required host
    )

    with pytest.raises(ValueError, match="http_host is required"):
        await client.connect()


@pytest.mark.asyncio
async def test_client_cloud_without_api_key_raises(query_config_file):
    """Test that Cloud client without API key raises error."""
    client = AsyncMultiCollectionQueryClient(
        config_path=query_config_file,
        client_type="cloud",
        cloud_api_key=None,  # Missing required API key
    )

    with pytest.raises(ValueError, match="cloud_api_key is required"):
        await client.connect()


@pytest.mark.asyncio
async def test_client_invalid_type_raises(query_config_file):
    """Test that invalid client type raises error."""
    client = AsyncMultiCollectionQueryClient(
        config_path=query_config_file,
        client_type="invalid",
    )

    with pytest.raises(ValueError, match="Unsupported client_type"):
        await client.connect()


@pytest.mark.asyncio
async def test_merge_results_sorting():
    """Test that results are properly merged and sorted by distance."""
    with TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.json"
        config_data = {
            "model_to_collections": {
                "Table": {
                    "collections": ["coll1", "coll2"],
                    "total_documents": 100,
                    "partitions": ["p1", "p2"],
                }
            },
            "collection_to_models": {
                "coll1": ["Table"],
                "coll2": ["Table"],
            },
            "metadata": {"total_models": 1, "total_collections": 2},
        }
        config_path.write_text(json.dumps(config_data))

        # Create mock client that returns different distances
        mock_client = AsyncMock()

        async def get_coll_side_effect(name, embedding_function=None):
            coll = AsyncMock()
            coll.name = name

            async def query_side_effect(*args, **kwargs):
                if name == "coll1":
                    return {
                        "ids": [["coll1_doc1", "coll1_doc2"]],
                        "distances": [[0.5, 0.7]],
                        "documents": [["doc1", "doc2"]],
                        "metadatas": [[{"m": 1}, {"m": 2}]],
                    }
                else:  # coll2
                    return {
                        "ids": [["coll2_doc1", "coll2_doc2"]],
                        "distances": [[0.3, 0.6]],  # Better scores
                        "documents": [["doc3", "doc4"]],
                        "metadatas": [[{"m": 3}, {"m": 4}]],
                    }

            coll.query = AsyncMock(side_effect=query_side_effect)
            return coll

        mock_client.get_collection = AsyncMock(side_effect=get_coll_side_effect)

        with patch("chromadb.AsyncHttpClient", return_value=mock_client):
            async with AsyncMultiCollectionQueryClient(
                config_path=config_path,
                client_type="http",
                http_host="localhost",
            ) as client:
                results = await client.query(
                    query_texts=["test"],
                    n_results=3,
                    models=["Table"],
                )

                # Check that results are sorted by distance
                distances = results["distances"][0]
                assert distances == sorted(distances)

                # Best result should be from coll2 (distance 0.3)
                assert results["ids"][0][0] == "coll2_doc1"
                assert results["distances"][0][0] == 0.3


@pytest.mark.asyncio
async def test_partial_failure_handling(query_config_file):
    """Test that partial collection failures are handled gracefully."""
    mock_client = AsyncMock()

    call_count = 0

    async def get_coll_side_effect(name, embedding_function=None):
        nonlocal call_count
        call_count += 1

        if call_count == 2:  # Second collection fails
            raise Exception("Connection timeout")

        coll = AsyncMock()
        coll.name = name

        async def query_side_effect(*args, **kwargs):
            return {
                "ids": [[f"{name}_doc"]],
                "distances": [[0.5]],
                "documents": [["doc"]],
                "metadatas": [[{"m": 1}]],
            }

        coll.query = AsyncMock(side_effect=query_side_effect)
        return coll

    mock_client.get_collection = AsyncMock(side_effect=get_coll_side_effect)

    with patch("chromadb.AsyncHttpClient", return_value=mock_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=query_config_file,
            client_type="http",
            http_host="localhost",
        ) as client:
            # Should not raise, just log warning
            results = await client.query(
                query_texts=["test"],
                n_results=5,
                models=["Table"],  # Queries 2 collections
            )

            # Should have results from successful collection(s)
            assert len(results["ids"][0]) > 0
