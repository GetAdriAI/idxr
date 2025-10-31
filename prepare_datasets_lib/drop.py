"""Model-centric drop planning and application helpers."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from ..models import ModelSpec

from .config import load_drop_config
from .manifest import load_manifest, save_manifest

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value)
        return datetime.fromisoformat(f"{value}T00:00:00")
    except ValueError:
        logging.warning("Could not parse date value '%s'; ignoring.", value)
        return None


@dataclass
class PlannedDrop:
    model: str
    partitions: List[str]
    schema_versions: List[int]


def generate_drop_config(
    *,
    manifest_path: Path,
    models: Iterable[str],
    before: Optional[str],
    after: Optional[str],
    default_reason: Optional[str],
) -> Tuple[Dict[str, object], List[PlannedDrop]]:
    """Create a drop configuration dictionary and summary from the manifest."""
    manifest = load_manifest(manifest_path)
    partitions = manifest.get("partitions", [])
    if not isinstance(partitions, list):
        raise ValueError("Manifest is missing a partitions list.")

    before_dt = _parse_date(before)
    after_dt = _parse_date(after)

    plan_models: Dict[str, Dict[str, object]] = {}
    summaries: List[PlannedDrop] = []

    for model in models:
        matched_partitions: List[str] = []
        schema_versions: set[int] = set()

        for entry in partitions:
            if not isinstance(entry, Mapping):
                continue
            partition_name = entry.get("name")
            if not partition_name:
                continue
            created_at_raw = entry.get("created_at")
            created_dt = (
                _parse_date(created_at_raw) if isinstance(created_at_raw, str) else None
            )
            if before_dt and created_dt and created_dt >= before_dt:
                continue
            if after_dt and created_dt and created_dt < after_dt:
                continue

            model_info = entry.get("models", {}).get(model)
            if not isinstance(model_info, Mapping):
                continue
            if model_info.get("deleted"):
                continue

            matched_partitions.append(partition_name)
            version = model_info.get("schema_version")
            if isinstance(version, int):
                schema_versions.add(version)

        if not matched_partitions:
            continue

        partitions_sorted = sorted(set(matched_partitions))
        plan_entry: Dict[str, object] = {
            "partitions": partitions_sorted,
        }
        schema_versions_sorted = sorted(schema_versions)
        if schema_versions_sorted:
            plan_entry["schema_versions"] = schema_versions_sorted
        if default_reason:
            plan_entry["reason"] = default_reason
        plan_models[model] = plan_entry
        summaries.append(
            PlannedDrop(
                model=model,
                partitions=partitions_sorted,
                schema_versions=schema_versions_sorted,
            )
        )

    plan: Dict[str, object] = {
        "generated_at": datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds"),
        "source_manifest": str(manifest_path.resolve()),
        "models": plan_models,
    }
    if before:
        plan["before"] = before
    if after:
        plan["after"] = after
    return plan, summaries


@dataclass
class DropResult:
    model: str
    partition: str
    rows: int
    reason: Optional[str]


def apply_drop_manifest(
    *,
    manifest_path: Path,
    drop_config_path: Path,
    apply_changes: bool,
    remove_local: bool = False,
    performed_by: Optional[str] = None,
    model_registry: Mapping[str, ModelSpec],
) -> List[DropResult]:
    """Mark models as dropped within the manifest (and optionally remove CSVs)."""
    manifest = load_manifest(manifest_path)
    drop_config, _ = load_drop_config(drop_config_path, model_registry=model_registry)

    partitions = manifest.get("partitions", [])
    if not isinstance(partitions, list):
        raise ValueError("Manifest is missing a partitions list.")

    partition_map: Dict[str, MutableMapping[str, object]] = {}
    for entry in partitions:
        if isinstance(entry, MutableMapping):
            name = entry.get("name")
            if isinstance(name, str):
                partition_map[name] = entry

    timestamp = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    )
    results: List[DropResult] = []

    for model_name, cfg in drop_config.items():
        for partition_name in cfg.partitions:
            entry = partition_map.get(partition_name)
            if not entry:
                logging.warning(
                    "Partition %s referenced in drop config but not found in manifest.",
                    partition_name,
                )
                continue
            model_info = entry.get("models", {}).get(model_name)
            if not isinstance(model_info, MutableMapping):
                logging.warning(
                    "Model %s not present in partition %s; skipping.",
                    model_name,
                    partition_name,
                )
                continue

            rows = int(model_info.get("rows", 0))
            already_deleted = bool(model_info.get("deleted"))
            if already_deleted and not apply_changes:
                # still include in dry-run summary for visibility
                results.append(
                    DropResult(
                        model=model_name,
                        partition=partition_name,
                        rows=rows,
                        reason=cfg.reason,
                    )
                )
                continue

            if apply_changes:
                if not already_deleted:
                    model_info["deleted"] = True
                    model_info["deleted_at"] = timestamp
                    if cfg.reason:
                        model_info["drop_reason"] = cfg.reason
                    if cfg.schema_versions:
                        model_info["drop_schema_versions"] = list(cfg.schema_versions)
                if remove_local:
                    csv_path = model_info.get("path")
                    if isinstance(csv_path, str):
                        try:
                            Path(csv_path).unlink(missing_ok=True)
                        except OSError as exc:
                            logging.warning(
                                "Failed to remove local file %s (%s)", csv_path, exc
                            )
            results.append(
                DropResult(
                    model=model_name,
                    partition=partition_name,
                    rows=rows,
                    reason=cfg.reason,
                )
            )

    if apply_changes:
        drops_log = manifest.setdefault("drops", [])
        if isinstance(drops_log, list):
            drops_log.append(
                {
                    "config": str(drop_config_path.resolve()),
                    "performed_at": timestamp,
                    "performed_by": performed_by or os.getenv("USER"),
                }
            )
        save_manifest(manifest_path, manifest)

    return results
