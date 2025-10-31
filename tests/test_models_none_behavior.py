"""Explicit tests to verify models=None behavior queries all collections."""

import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient
from indexer.vectorize_lib.query_config import (
    generate_query_config,
    get_collections_for_models,
)


@pytest.fixture
def multi_partition_setup():
    """Create a setup with 5 partitions and 3 models."""
    with TemporaryDirectory() as tmpdir:
        partition_out_dir = Path(tmpdir) / "vector"
        partition_out_dir.mkdir()

        # Create 5 partitions with different models
        for i in range(1, 6):
            partition = partition_out_dir / f"partition_{i:05d}"
            partition.mkdir()

            # Distribute models across partitions
            models_in_partition = {}
            if i in [1, 2]:
                models_in_partition["Table"] = {
                    "started": True,
                    "collection_count": 100,
                }
            if i in [2, 3, 4]:
                models_in_partition["Field"] = {
                    "started": True,
                    "collection_count": 200,
                }
            if i in [4, 5]:
                models_in_partition["Domain"] = {
                    "started": True,
                    "collection_count": 150,
                }

            resume_file = partition / f"partition_{i:05d}_resume_state.json"
            resume_file.write_text(json.dumps(models_in_partition), encoding="utf-8")

        # Generate config
        config = generate_query_config(partition_out_dir)
        config_path = Path(tmpdir) / "query_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        yield {
            "config": config,
            "config_path": config_path,
            "total_partitions": 5,
            "models": {
                "Table": ["partition_00001", "partition_00002"],
                "Field": ["partition_00002", "partition_00003", "partition_00004"],
                "Domain": ["partition_00004", "partition_00005"],
            },
        }


def test_get_collections_none_returns_all(multi_partition_setup):
    """Test that get_collections_for_models(config, None) returns ALL collections."""
    config = multi_partition_setup["config"]

    # When models=None, should return all 5 collections
    collections = get_collections_for_models(config, None)

    assert len(collections) == 5
    assert set(collections) == {
        "partition_00001",
        "partition_00002",
        "partition_00003",
        "partition_00004",
        "partition_00005",
    }


def test_get_collections_empty_list_returns_all(multi_partition_setup):
    """Test that get_collections_for_models(config, []) returns ALL collections."""
    config = multi_partition_setup["config"]

    # When models=[], should return all 5 collections
    collections = get_collections_for_models(config, [])

    assert len(collections) == 5
    assert set(collections) == {
        "partition_00001",
        "partition_00002",
        "partition_00003",
        "partition_00004",
        "partition_00005",
    }


def test_get_collections_specific_model_subset(multi_partition_setup):
    """Test that specifying models returns only relevant collections."""
    config = multi_partition_setup["config"]

    # Table is only in 2 collections
    collections = get_collections_for_models(config, ["Table"])
    assert set(collections) == {"partition_00001", "partition_00002"}

    # Field is in 3 collections
    collections = get_collections_for_models(config, ["Field"])
    assert set(collections) == {"partition_00002", "partition_00003", "partition_00004"}

    # Domain is in 2 collections
    collections = get_collections_for_models(config, ["Domain"])
    assert set(collections) == {"partition_00004", "partition_00005"}


def test_get_collections_multiple_models_union(multi_partition_setup):
    """Test that multiple models return union of their collections."""
    config = multi_partition_setup["config"]

    # Table + Domain should return union of their collections
    collections = get_collections_for_models(config, ["Table", "Domain"])
    assert set(collections) == {
        "partition_00001",
        "partition_00002",
        "partition_00004",
        "partition_00005",
    }

    # All 3 models should return all 5 collections
    collections = get_collections_for_models(config, ["Table", "Field", "Domain"])
    assert len(collections) == 5


@pytest.mark.asyncio
async def test_query_models_none_fans_to_all_collections(multi_partition_setup):
    """Test that query with models=None queries ALL collections."""
    config_path = multi_partition_setup["config_path"]

    mock_client = AsyncMock()
    mock_collections_accessed = []

    async def get_collection_side_effect(name, embedding_function=None):
        mock_collections_accessed.append(name)
        collection = AsyncMock()
        collection.name = name

        async def query_side_effect(*args, **kwargs):
            return {
                "ids": [[f"{name}_doc1"]],
                "distances": [[0.5]],
                "documents": [["test doc"]],
                "metadatas": [[{"model": "test"}]],
            }

        collection.query = AsyncMock(side_effect=query_side_effect)
        return collection

    mock_client.get_collection = AsyncMock(side_effect=get_collection_side_effect)

    with patch("chromadb.AsyncHttpClient", return_value=mock_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=config_path,
            client_type="http",
            http_host="localhost",
        ) as client:
            # Query with models=None
            results = await client.query(
                query_texts=["test query"],
                n_results=10,
                models=None,  # Should query ALL 5 collections
            )

            # Verify all 5 collections were accessed
            assert len(mock_collections_accessed) == 5
            assert set(mock_collections_accessed) == {
                "partition_00001",
                "partition_00002",
                "partition_00003",
                "partition_00004",
                "partition_00005",
            }

            # Verify we got results
            assert len(results["ids"][0]) > 0


@pytest.mark.asyncio
async def test_query_models_specific_fans_to_subset(multi_partition_setup):
    """Test that query with specific models only queries those collections."""
    config_path = multi_partition_setup["config_path"]

    mock_client = AsyncMock()
    mock_collections_accessed = []

    async def get_collection_side_effect(name, embedding_function=None):
        mock_collections_accessed.append(name)
        collection = AsyncMock()
        collection.name = name

        async def query_side_effect(*args, **kwargs):
            return {
                "ids": [[f"{name}_doc1"]],
                "distances": [[0.5]],
                "documents": [["test doc"]],
                "metadatas": [[{"model": "test"}]],
            }

        collection.query = AsyncMock(side_effect=query_side_effect)
        return collection

    mock_client.get_collection = AsyncMock(side_effect=get_collection_side_effect)

    with patch("chromadb.AsyncHttpClient", return_value=mock_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=config_path,
            client_type="http",
            http_host="localhost",
        ) as client:
            # Query with models=["Table"] - should only query 2 collections
            await client.query(
                query_texts=["test query"],
                n_results=10,
                models=["Table"],  # Only Table's collections
            )

            # Verify only Table's 2 collections were accessed
            assert len(mock_collections_accessed) == 2
            assert set(mock_collections_accessed) == {
                "partition_00001",
                "partition_00002",
            }


@pytest.mark.asyncio
async def test_count_models_none_counts_all(multi_partition_setup):
    """Test that count with models=None counts ALL collections."""
    config_path = multi_partition_setup["config_path"]

    mock_client = AsyncMock()
    mock_collections_accessed = []

    async def get_collection_side_effect(name, embedding_function=None):
        mock_collections_accessed.append(name)
        collection = AsyncMock()
        collection.count = AsyncMock(return_value=100)
        return collection

    mock_client.get_collection = AsyncMock(side_effect=get_collection_side_effect)

    with patch("chromadb.AsyncHttpClient", return_value=mock_client):
        async with AsyncMultiCollectionQueryClient(
            config_path=config_path,
            client_type="http",
            http_host="localhost",
        ) as client:
            # Count with models=None
            total = await client.count(models=None)

            # Should have counted all 5 collections
            assert len(mock_collections_accessed) == 5
            assert total == 500  # 100 per collection × 5


def test_behavior_documented_correctly(multi_partition_setup):
    """Verify the documented behavior matches implementation."""
    config = multi_partition_setup["config"]

    # From documentation: "If models is None, queries all collections"
    all_collections = get_collections_for_models(config, None)
    assert len(all_collections) == 5, "models=None should return all collections"

    # From documentation: model filtering reduces collections queried
    subset = get_collections_for_models(config, ["Table"])
    assert len(subset) < len(all_collections), "Specific models should query subset"
