"""Manifest utilities for prepare_datasets."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Mapping, Optional, Sequence, Set

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "manifest.json"
ROW_DIGEST_DELIMITER = "\u241f"


def compute_row_digest(values: Sequence[Optional[str]]) -> str:
    """Return the deterministic digest used to detect duplicate rows."""
    payload = ROW_DIGEST_DELIMITER.join(
        "" if value is None else str(value) for value in values
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> Dict[str, Any]:
    """Load the partition manifest, returning an empty template if missing."""
    if not path.exists():
        return {
            "version": MANIFEST_VERSION,
            "partitions": [],
            "runs": [],
        }
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Manifest file must contain a JSON object")
    if raw.get("version") != MANIFEST_VERSION:
        raise ValueError(
            f"Unsupported manifest version {raw.get('version')}; expected {MANIFEST_VERSION}"
        )
    raw.setdefault("partitions", [])
    raw.setdefault("runs", [])
    raw.setdefault("model_schemas", {})
    return raw


def save_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Persist the manifest to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def load_existing_hashes(manifest: Mapping[str, Any]) -> DefaultDict[str, Set[str]]:
    """Rehydrate row digests from previous runs so new data can be deduplicated."""
    seen: DefaultDict[str, Set[str]] = defaultdict(set)
    partitions = manifest.get("partitions", [])
    if not isinstance(partitions, list):
        logging.warning("Manifest 'partitions' entry is not a list; ignoring.")
        return seen
    for entry in partitions:
        if not isinstance(entry, Mapping):
            continue
        models = entry.get("models", {})
        if not isinstance(models, Mapping):
            continue
        for model_name, model_info in models.items():
            if not isinstance(model_info, Mapping):
                continue
            path_value = model_info.get("path")
            if not isinstance(path_value, str):
                continue
            csv_path = Path(path_value)
            if not csv_path.exists():
                logging.debug(
                    "Skipping missing partition CSV %s during hash load.",
                    csv_path,
                )
                continue
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.reader(handle)
                    headers = next(reader, None)
                    if not headers:
                        continue
                    header_count = len(headers)
                    for row in reader:
                        values: List[Optional[str]] = []
                        for idx in range(header_count):
                            if idx < len(row):
                                cell = row[idx]
                                values.append(cell if cell != "" else "")
                            else:
                                values.append("")
                        seen[model_name].add(compute_row_digest(values))
            except OSError as exc:
                logging.warning(
                    "Failed to load existing hashes from %s: %s",
                    csv_path,
                    exc,
                )
    return seen
