"""Generate and manage query configuration for multi-collection ChromaDB setups."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

logger = logging.getLogger(__name__)


def generate_query_config(
    partition_out_dir: Path,
    *,
    output_path: Optional[Path] = None,
    collection_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate query configuration by scanning resume state files.

    Args:
        partition_out_dir: Directory containing partition subdirectories
        output_path: Optional path to write the query config JSON file
        collection_prefix: Optional prefix used for collection names

    Returns:
        Dictionary mapping model names to their collections with metadata

    The generated config has the structure:
    {
        "model_to_collections": {
            "ModelName": {
                "collections": ["collection_1", "collection_2"],
                "total_documents": 12345,
                "partitions": ["partition_00001", "partition_00002"]
            }
        },
        "collection_to_models": {
            "collection_1": ["ModelName1", "ModelName2"]
        },
        "metadata": {
            "total_collections": 10,
            "total_models": 5,
            "generated_at": "2025-10-31T12:00:00"
        }
    }
    """
    from datetime import datetime, timezone

    if not partition_out_dir.exists() or not partition_out_dir.is_dir():
        raise ValueError(
            f"Partition output directory {partition_out_dir} does not exist "
            "or is not a directory"
        )

    # Map model_name -> {collections: Set[str], documents: int, partitions: Set[str]}
    model_info: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"collections": set(), "documents": 0, "partitions": set()}
    )

    # Map collection_name -> Set[model_name]
    collection_to_models: Dict[str, Set[str]] = defaultdict(set)

    # Track all collections we've seen
    all_collections: Set[str] = set()

    # Scan each partition directory
    partition_dirs = sorted(
        [entry for entry in partition_out_dir.iterdir() if entry.is_dir()],
        key=lambda p: p.name,
    )

    if not partition_dirs:
        logger.warning("No partition subdirectories found in %s", partition_out_dir)

    for partition_dir in partition_dirs:
        partition_name = partition_dir.name

        # Find all resume state files in this partition directory
        resume_files = list(partition_dir.glob("*_resume_state.json"))

        if not resume_files:
            logger.debug("No resume state files found in partition %s", partition_name)
            continue

        for resume_file in resume_files:
            try:
                resume_data = json.loads(resume_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Failed to read resume state file %s: %s", resume_file, exc
                )
                continue

            if not isinstance(resume_data, dict):
                logger.warning(
                    "Resume state file %s does not contain a JSON object", resume_file
                )
                continue

            # Extract collection name from filename
            # Format: <collection_name>_resume_state.json
            filename = resume_file.stem  # Remove .json
            if filename.endswith("_resume_state"):
                collection_name = filename[: -len("_resume_state")]
            else:
                logger.warning(
                    "Unexpected resume state filename format: %s", resume_file.name
                )
                continue

            all_collections.add(collection_name)

            # Process each model in the resume state
            for model_name, model_state in resume_data.items():
                if not isinstance(model_state, Mapping):
                    continue

                # Check if this model was completed (not in error state)
                if not model_state.get("started"):
                    continue

                # Check if model has been indexed (collection_count > 0)
                collection_count = model_state.get("collection_count", 0)
                if not isinstance(collection_count, int) or collection_count <= 0:
                    continue

                # Add this collection to the model's collection list
                model_info[model_name]["collections"].add(collection_name)
                model_info[model_name]["documents"] += collection_count
                model_info[model_name]["partitions"].add(partition_name)

                # Add this model to the collection's model list
                collection_to_models[collection_name].add(model_name)

    # Convert sets to sorted lists for JSON serialization
    model_to_collections: Dict[str, Dict[str, Any]] = {}
    for model_name, info in model_info.items():
        model_to_collections[model_name] = {
            "collections": sorted(info["collections"]),
            "total_documents": info["documents"],
            "partitions": sorted(info["partitions"]),
        }

    collection_to_models_serialized: Dict[str, List[str]] = {
        coll: sorted(models) for coll, models in collection_to_models.items()
    }

    # Build metadata
    metadata = {
        "total_collections": len(all_collections),
        "total_models": len(model_to_collections),
        "generated_at": datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds"),
        "partition_out_dir": str(partition_out_dir.resolve()),
    }

    if collection_prefix:
        metadata["collection_prefix"] = collection_prefix

    query_config = {
        "model_to_collections": model_to_collections,
        "collection_to_models": collection_to_models_serialized,
        "metadata": metadata,
    }

    # Write to file if output_path is specified
    if output_path is not None:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(query_config, indent=2, sort_keys=False),
                encoding="utf-8",
            )
            logger.info("Query config written to %s", output_path)
        except OSError as exc:
            logger.error("Failed to write query config to %s: %s", output_path, exc)
            raise

    return query_config


def load_query_config(config_path: Path) -> Dict[str, Any]:
    """Load query configuration from a JSON file.

    Args:
        config_path: Path to the query config JSON file

    Returns:
        Dictionary containing the query configuration

    Raises:
        ValueError: If the config file doesn't exist or is invalid
    """
    if not config_path.exists():
        raise ValueError(f"Query config file {config_path} does not exist")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Failed to read query config from {config_path}: {exc}"
        ) from exc

    if not isinstance(config, dict):
        raise ValueError(
            f"Query config file {config_path} does not contain a JSON object"
        )

    # Validate required keys
    required_keys = ["model_to_collections", "collection_to_models", "metadata"]
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        raise ValueError(
            f"Query config missing required keys: {', '.join(missing_keys)}"
        )

    return config


def get_collections_for_models(
    query_config: Dict[str, Any],
    model_names: Optional[List[str]] = None,
) -> List[str]:
    """Get list of collections that need to be queried for given models.

    Args:
        query_config: Query configuration dictionary
        model_names: List of model names to query, or None for all collections

    Returns:
        Sorted list of collection names to query
    """
    if model_names is None or len(model_names) == 0:
        # Query all collections
        return sorted(query_config["collection_to_models"].keys())

    collections: Set[str] = set()
    model_to_collections = query_config["model_to_collections"]

    for model_name in model_names:
        if model_name not in model_to_collections:
            logger.warning("Model %s not found in query config; skipping", model_name)
            continue

        model_colls = model_to_collections[model_name]["collections"]
        collections.update(model_colls)

    return sorted(collections)
