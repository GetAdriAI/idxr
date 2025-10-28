"""Manifest handling for partition-based indexing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Mapping, Tuple

PARTITION_MANIFEST_VERSION = 1


def load_partition_manifest_entries(
    manifest_path: Path, default_config_name: str
) -> List[Tuple[str, Path, Path]]:
    """Return ordered partition manifest entries (name, directory, config path)."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("Partition manifest must contain a JSON object.")
    version = raw.get("version")
    if version not in (None, PARTITION_MANIFEST_VERSION):
        raise ValueError(
            f"Unsupported partition manifest version {version}; "
            f"expected {PARTITION_MANIFEST_VERSION}."
        )
    partitions = raw.get("partitions")
    if not isinstance(partitions, list):
        raise ValueError("Partition manifest is missing a 'partitions' array.")

    base_dir = manifest_path.parent
    entries: List[Tuple[str, Path, Path]] = []
    for index, item in enumerate(partitions):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"Partition manifest entry at index {index} must be an object."
            )
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"Partition manifest entry at index {index} is missing a valid 'name'."
            )
        path_value = item.get("path")
        if isinstance(path_value, str) and path_value:
            partition_dir = Path(path_value)
            if not partition_dir.is_absolute():
                partition_dir = (base_dir / partition_dir).resolve()
        else:
            partition_dir = (base_dir / name).resolve()

        config_value = item.get("config")
        if isinstance(config_value, str) and config_value:
            config_path = Path(config_value)
            if not config_path.is_absolute():
                config_path = (base_dir / config_path).resolve()
        else:
            config_path = partition_dir / default_config_name

        entries.append((name, partition_dir, config_path))
    return entries
