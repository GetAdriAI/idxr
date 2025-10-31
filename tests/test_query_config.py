"""Tests for query configuration generation."""

import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from indexer.vectorize_lib.query_config import (
    generate_query_config,
    load_query_config,
    get_collections_for_models,
)


@pytest.fixture
def temp_partition_dir():
    """Create a temporary partition directory structure."""
    with TemporaryDirectory() as tmpdir:
        partition_out_dir = Path(tmpdir) / "vector"
        partition_out_dir.mkdir()
        yield partition_out_dir


@pytest.fixture
def populated_partition_dir(temp_partition_dir):
    """Create a partition directory with mock resume state files."""

    # Partition 1: Table and Field models
    partition_1 = temp_partition_dir / "partition_00001"
    partition_1.mkdir()

    resume_state_1 = {
        "Table": {
            "started": True,
            "complete": True,
            "collection_count": 1000,
            "documents_indexed": 1000,
            "indexed_at": "2025-10-31T10:00:00",
        },
        "Field": {
            "started": True,
            "complete": False,
            "collection_count": 500,
            "documents_indexed": 500,
            "indexed_at": "2025-10-31T10:30:00",
        },
    }
    (partition_1 / "partition_00001_resume_state.json").write_text(
        json.dumps(resume_state_1), encoding="utf-8"
    )

    # Partition 2: Field and Domain models
    partition_2 = temp_partition_dir / "partition_00002"
    partition_2.mkdir()

    resume_state_2 = {
        "Field": {
            "started": True,
            "complete": True,
            "collection_count": 800,
            "documents_indexed": 800,
            "indexed_at": "2025-10-31T11:00:00",
        },
        "Domain": {
            "started": True,
            "complete": True,
            "collection_count": 300,
            "documents_indexed": 300,
            "indexed_at": "2025-10-31T11:30:00",
        },
    }
    (partition_2 / "partition_00002_resume_state.json").write_text(
        json.dumps(resume_state_2), encoding="utf-8"
    )

    # Partition 3: Model with no documents (should be excluded)
    partition_3 = temp_partition_dir / "partition_00003"
    partition_3.mkdir()

    resume_state_3 = {
        "EmptyModel": {
            "started": True,
            "complete": True,
            "collection_count": 0,  # No documents
            "documents_indexed": 0,
        },
        "NotStarted": {
            "started": False,  # Not started
            "collection_count": 100,
        },
    }
    (partition_3 / "partition_00003_resume_state.json").write_text(
        json.dumps(resume_state_3), encoding="utf-8"
    )

    return temp_partition_dir


def test_generate_query_config_empty_dir(temp_partition_dir):
    """Test generating config from empty directory."""
    config = generate_query_config(temp_partition_dir)

    assert config["metadata"]["total_models"] == 0
    assert config["metadata"]["total_collections"] == 0
    assert config["model_to_collections"] == {}
    assert config["collection_to_models"] == {}


def test_generate_query_config_with_data(populated_partition_dir):
    """Test generating config with populated partitions."""
    config = generate_query_config(populated_partition_dir)

    # Check metadata
    assert config["metadata"]["total_models"] == 3  # Table, Field, Domain
    # total_collections counts all resume state files found, even if they have no valid models
    assert (
        config["metadata"]["total_collections"] == 3
    )  # partition_00001, partition_00002, partition_00003
    assert "generated_at" in config["metadata"]

    # Check model_to_collections
    model_to_collections = config["model_to_collections"]

    # Table should be in partition_00001 only
    assert "Table" in model_to_collections
    assert model_to_collections["Table"]["collections"] == ["partition_00001"]
    assert model_to_collections["Table"]["total_documents"] == 1000
    assert model_to_collections["Table"]["partitions"] == ["partition_00001"]

    # Field should be in both partitions
    assert "Field" in model_to_collections
    assert set(model_to_collections["Field"]["collections"]) == {
        "partition_00001",
        "partition_00002",
    }
    assert model_to_collections["Field"]["total_documents"] == 1300  # 500 + 800
    assert set(model_to_collections["Field"]["partitions"]) == {
        "partition_00001",
        "partition_00002",
    }

    # Domain should be in partition_00002 only
    assert "Domain" in model_to_collections
    assert model_to_collections["Domain"]["collections"] == ["partition_00002"]
    assert model_to_collections["Domain"]["total_documents"] == 300

    # EmptyModel and NotStarted should not be included
    assert "EmptyModel" not in model_to_collections
    assert "NotStarted" not in model_to_collections

    # Check collection_to_models
    collection_to_models = config["collection_to_models"]

    assert set(collection_to_models["partition_00001"]) == {"Table", "Field"}
    assert set(collection_to_models["partition_00002"]) == {"Field", "Domain"}
    assert "partition_00003" not in collection_to_models


def test_generate_query_config_with_output(populated_partition_dir):
    """Test generating config and writing to file."""
    output_path = populated_partition_dir / "query_config.json"

    config = generate_query_config(
        populated_partition_dir,
        output_path=output_path,
    )

    # Verify file was written
    assert output_path.exists()

    # Verify file contents
    loaded_config = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded_config == config


def test_generate_query_config_with_prefix(populated_partition_dir):
    """Test generating config with collection prefix."""
    config = generate_query_config(
        populated_partition_dir,
        collection_prefix="ecc-std",
    )

    assert config["metadata"]["collection_prefix"] == "ecc-std"


def test_load_query_config(populated_partition_dir):
    """Test loading query config from file."""
    output_path = populated_partition_dir / "query_config.json"

    # Generate and save
    original_config = generate_query_config(
        populated_partition_dir,
        output_path=output_path,
    )

    # Load
    loaded_config = load_query_config(output_path)

    assert loaded_config == original_config
    assert "model_to_collections" in loaded_config
    assert "collection_to_models" in loaded_config
    assert "metadata" in loaded_config


def test_load_query_config_missing_file(temp_partition_dir):
    """Test loading config from non-existent file."""
    missing_path = temp_partition_dir / "missing.json"

    with pytest.raises(ValueError, match="does not exist"):
        load_query_config(missing_path)


def test_load_query_config_invalid_json(temp_partition_dir):
    """Test loading config from invalid JSON."""
    invalid_path = temp_partition_dir / "invalid.json"
    invalid_path.write_text("not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to read"):
        load_query_config(invalid_path)


def test_load_query_config_missing_keys(temp_partition_dir):
    """Test loading config with missing required keys."""
    incomplete_path = temp_partition_dir / "incomplete.json"
    incomplete_path.write_text(
        json.dumps({"model_to_collections": {}}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="missing required keys"):
        load_query_config(incomplete_path)


def test_get_collections_for_models_specific(populated_partition_dir):
    """Test getting collections for specific models."""
    config = generate_query_config(populated_partition_dir)

    # Get collections for Table only
    collections = get_collections_for_models(config, ["Table"])
    assert collections == ["partition_00001"]

    # Get collections for Field only
    collections = get_collections_for_models(config, ["Field"])
    assert set(collections) == {"partition_00001", "partition_00002"}

    # Get collections for Table and Domain
    collections = get_collections_for_models(config, ["Table", "Domain"])
    assert set(collections) == {"partition_00001", "partition_00002"}


def test_get_collections_for_models_all(populated_partition_dir):
    """Test getting all collections."""
    config = generate_query_config(populated_partition_dir)

    # None means all collections
    collections = get_collections_for_models(config, None)
    assert set(collections) == {"partition_00001", "partition_00002"}

    # Empty list also means all collections
    collections = get_collections_for_models(config, [])
    assert set(collections) == {"partition_00001", "partition_00002"}


def test_get_collections_for_models_unknown(populated_partition_dir):
    """Test getting collections for unknown model."""
    config = generate_query_config(populated_partition_dir)

    # Unknown model should return empty list (with warning logged)
    collections = get_collections_for_models(config, ["UnknownModel"])
    assert collections == []


def test_get_collections_for_models_mixed(populated_partition_dir):
    """Test getting collections with mix of known and unknown models."""
    config = generate_query_config(populated_partition_dir)

    # Mix of known and unknown
    collections = get_collections_for_models(
        config, ["Table", "UnknownModel", "Domain"]
    )
    assert set(collections) == {"partition_00001", "partition_00002"}


def test_generate_query_config_malformed_resume_file(temp_partition_dir):
    """Test handling malformed resume state file."""
    partition = temp_partition_dir / "partition_00001"
    partition.mkdir()

    # Write malformed JSON
    (partition / "partition_00001_resume_state.json").write_text(
        "not valid json", encoding="utf-8"
    )

    # Should not crash, just skip the file
    config = generate_query_config(temp_partition_dir)
    assert config["metadata"]["total_models"] == 0


def test_generate_query_config_non_dict_resume_data(temp_partition_dir):
    """Test handling resume state that's not a dict."""
    partition = temp_partition_dir / "partition_00001"
    partition.mkdir()

    # Write array instead of dict
    (partition / "partition_00001_resume_state.json").write_text(
        json.dumps(["not", "a", "dict"]), encoding="utf-8"
    )

    # Should not crash, just skip the file
    config = generate_query_config(temp_partition_dir)
    assert config["metadata"]["total_models"] == 0


def test_generate_query_config_invalid_model_state(temp_partition_dir):
    """Test handling invalid model state data."""
    partition = temp_partition_dir / "partition_00001"
    partition.mkdir()

    resume_state = {
        "ValidModel": {
            "started": True,
            "collection_count": 100,
        },
        "InvalidModel": "not a dict",  # Invalid
        "NoCountModel": {
            "started": True,
            # Missing collection_count
        },
    }
    (partition / "partition_00001_resume_state.json").write_text(
        json.dumps(resume_state), encoding="utf-8"
    )

    config = generate_query_config(temp_partition_dir)

    # Only ValidModel should be included
    assert config["metadata"]["total_models"] == 1
    assert "ValidModel" in config["model_to_collections"]
    assert "InvalidModel" not in config["model_to_collections"]
    assert "NoCountModel" not in config["model_to_collections"]


def test_generate_query_config_collections_sorted(populated_partition_dir):
    """Test that collections are sorted in the output."""
    config = generate_query_config(populated_partition_dir)

    # Field is in both partitions - verify they're sorted
    field_collections = config["model_to_collections"]["Field"]["collections"]
    assert field_collections == sorted(field_collections)

    # Verify collection_to_models keys are sorted
    collection_keys = list(config["collection_to_models"].keys())
    assert collection_keys == sorted(collection_keys)


def test_generate_query_config_nonexistent_dir():
    """Test generating config from non-existent directory."""
    with pytest.raises(ValueError, match="does not exist"):
        generate_query_config(Path("/nonexistent/path"))


def test_generate_query_config_file_instead_of_dir(temp_partition_dir):
    """Test generating config from file path instead of directory."""
    file_path = temp_partition_dir / "somefile.txt"
    file_path.write_text("content")

    with pytest.raises(ValueError, match="not a directory"):
        generate_query_config(file_path)
