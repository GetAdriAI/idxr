"""Configuration helpers for prepare_datasets."""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from kb.std.ecc_6_0_ehp_7.registry import ModelSpec


DEFAULT_CONFIG_OUTPUT_DIR = Path("prepare_datasets")
DEFAULT_CONFIG_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"


@dataclass
class PrepModelConfig:
    """User-supplied preprocessing directives for a single Pydantic model."""

    path: Optional[Path]
    columns: Dict[str, str]
    character_encoding: str
    delimiter: str
    malformed_column: Optional[int]
    header_row: str
    drop_na_columns: Sequence[str]


def list_model_fields(
    model_name: str, *, model_registry: Mapping[str, ModelSpec]
) -> List[str]:
    """Return the field names for the given model."""
    spec = model_registry[model_name]
    model_cls = spec.model
    model_fields = getattr(model_cls, "model_fields", None)
    if model_fields is None:
        model_fields = getattr(model_cls, "__fields__", {})
    if isinstance(model_fields, dict):
        return list(model_fields.keys())
    return []


def slugify_name(name: str) -> str:
    """Return a filesystem-friendly slug for the config name."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "config"


def generate_config_stub(
    models: Sequence[str], *, model_registry: Mapping[str, ModelSpec]
) -> Dict[str, object]:
    """Create the JSON structure for a prepare_datasets config stub."""
    config: Dict[str, object] = {}
    for model_name in models:
        fields = list_model_fields(model_name, model_registry=model_registry)
        config[model_name] = {
            "path": "",
            "columns": {field: field for field in fields},
            "character_encoding": "utf-8",
            "delimiter": ",",
            "malformed_column": None,
            "header_row": "all",
            "drop_na_columns": [],
        }
    return config


@dataclass
class DropModelConfig:
    """Describes how an indexed model should be removed."""

    partitions: List[str]
    schema_versions: Optional[List[int]]
    reason: Optional[str]


def get_model_schema_signature(
    model_name: str, *, model_registry: Mapping[str, ModelSpec]
) -> str:
    """Return a stable hash representing the schema of the given model."""
    spec = model_registry[model_name]
    model_cls = spec.model

    def _field_entries(field_map: Mapping[str, object]) -> List[Dict[str, object]]:
        entries: List[Dict[str, object]] = []
        for name, field in sorted(field_map.items(), key=lambda item: item[0]):
            entry: Dict[str, object] = {"name": name}
            annotation = getattr(field, "annotation", None)
            outer = getattr(field, "outer_type_", None)
            entry["type"] = repr(annotation or outer)
            alias = getattr(field, "alias", None)
            if alias:
                entry["alias"] = alias
            required = getattr(field, "is_required", None)
            if required is None:
                required = getattr(field, "required", None)
            if required is not None:
                entry["required"] = bool(required)
            default = getattr(field, "default", None)
            if default not in (None, ...):
                entry["default"] = repr(default)
            entries.append(entry)
        return entries

    field_map = getattr(model_cls, "model_fields", None)
    if isinstance(field_map, Mapping):
        field_entries = _field_entries(field_map)
    else:
        legacy_fields = getattr(model_cls, "__fields__", {})
        if isinstance(legacy_fields, Mapping):
            field_entries = _field_entries(legacy_fields)
        else:
            field_entries = []

    payload = {
        "model": f"{model_cls.__module__}.{model_cls.__name__}",
        "fields": field_entries,
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest


def load_prep_config(
    config_path: Path, *, model_registry: Mapping[str, ModelSpec]
) -> Dict[str, PrepModelConfig]:
    """Load a preprocessing JSON config that mirrors the vectorize config with extras."""
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Configuration file must contain a JSON object")

    cleaned: Dict[str, PrepModelConfig] = {}
    for model_name, entry in raw.items():
        if model_name not in model_registry:
            raise KeyError(f"Unknown model '{model_name}' in configuration.")
        if entry in (None, "", []):
            cleaned[model_name] = PrepModelConfig(
                path=None,
                columns={},
                character_encoding="utf-8",
                delimiter=",",
                malformed_column=None,
                header_row="all",
                drop_na_columns=(),
            )
            continue
        if isinstance(entry, str):
            cleaned[model_name] = PrepModelConfig(
                path=Path(entry).expanduser(),
                columns={},
                character_encoding="utf-8",
                delimiter=",",
                malformed_column=None,
                header_row="all",
                drop_na_columns=(),
            )
            continue
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"Configuration value for '{model_name}' must be a string, object, or null"
            )

        raw_path = entry.get("path")
        if raw_path in (None, "", []):
            source_path = None
        else:
            source_path = Path(str(raw_path)).expanduser()

        columns = entry.get("columns", {})
        if not isinstance(columns, Mapping):
            raise ValueError(
                f"Configuration value for '{model_name}.columns' must be an object"
            )
        normalized_columns: Dict[str, str] = {}
        for target, source in columns.items():
            if not isinstance(target, str) or not isinstance(source, str):
                raise ValueError(
                    f"Configuration value for '{model_name}.columns' must map "
                    "strings to strings"
                )
            normalized_columns[target] = source

        encoding = entry.get("character_encoding", "utf-8")
        if not isinstance(encoding, str):
            raise ValueError(
                f"Configuration value for '{model_name}.character_encoding' must be a string"
            )

        delimiter = entry.get("delimiter", ",")
        if not isinstance(delimiter, str) or not delimiter:
            raise ValueError(
                f"Configuration value for '{model_name}.delimiter' must be a non-empty string"
            )

        malformed_value = entry.get("malformed_column")
        malformed_column = None
        if malformed_value not in (None, ""):
            if isinstance(malformed_value, int) and malformed_value >= 1:
                malformed_column = malformed_value
            else:
                raise ValueError(
                    f"Configuration value for '{model_name}.malformed_column' "
                    "must be a positive int"
                )

        header_row = entry.get("header_row", "all")
        if header_row not in ("all", "first-only"):
            raise ValueError(
                f"Configuration value for '{model_name}.header_row' must be "
                "'all' or 'first-only'"
            )

        drop_na_columns = entry.get("drop_na_columns", [])
        if drop_na_columns in (None, "", []):
            drop_na_columns = ()
        elif isinstance(drop_na_columns, Sequence) and all(
            isinstance(col, str) for col in drop_na_columns
        ):
            drop_na_columns = tuple(drop_na_columns)
        else:
            raise ValueError(
                f"Configuration value for '{model_name}.drop_na_columns' must "
                "be an array of strings"
            )

        cleaned[model_name] = PrepModelConfig(
            path=source_path,
            columns=normalized_columns,
            character_encoding=encoding,
            delimiter=delimiter,
            malformed_column=malformed_column,
            header_row=header_row,
            drop_na_columns=drop_na_columns,
        )
    return cleaned


def load_drop_config(
    config_path: Path,
    *,
    model_registry: Mapping[str, ModelSpec],
) -> Tuple[Dict[str, DropModelConfig], Dict[str, object]]:
    """Load a model-centric drop configuration."""
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Drop configuration must be a JSON object.")
    models_entry = raw.get("models")
    if not isinstance(models_entry, Mapping):
        raise ValueError("Drop configuration missing 'models' mapping.")

    drop_configs: Dict[str, DropModelConfig] = {}
    for model_name, entry in models_entry.items():
        if model_name not in model_registry:
            raise KeyError(f"Unknown model '{model_name}' in drop configuration.")
        if not isinstance(entry, Mapping):
            raise ValueError(
                f"Drop configuration for '{model_name}' must be an object."
            )
        partitions_value = entry.get("partitions", [])
        if not isinstance(partitions_value, Sequence):
            raise ValueError(
                f"'partitions' for '{model_name}' must be an array of strings."
            )
        partitions = [str(item) for item in partitions_value if str(item)]

        schema_versions_value = entry.get("schema_versions")
        if schema_versions_value in (None, "", []):
            schema_versions: Optional[List[int]] = None
        elif isinstance(schema_versions_value, Sequence):
            schema_versions = [
                int(value) for value in schema_versions_value if str(value)
            ]
        else:
            raise ValueError(
                f"'schema_versions' for '{model_name}' must be an array of integers."
            )

        reason_value = entry.get("reason")
        if reason_value in (None, ""):
            reason = None
        elif isinstance(reason_value, str):
            reason = reason_value
        else:
            raise ValueError(
                f"'reason' for '{model_name}' must be a string if provided."
            )

        drop_configs[model_name] = DropModelConfig(
            partitions=partitions,
            schema_versions=schema_versions,
            reason=reason,
        )

    metadata: Dict[str, object] = {
        key: value for key, value in raw.items() if key != "models"
    }
    return drop_configs, metadata
