"""Config loading and stubbing for vectorize."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional

from indexer.models import ModelSpec


@dataclass
class ModelConfig:
    """User-provided configuration for loading a model's CSV export."""

    path: Optional[Path]
    columns: Dict[str, str]


def load_config(
    config_path: Path, model_registry: Mapping[str, ModelSpec]
) -> Dict[str, ModelConfig]:
    """Load the model-to-CSV mapping from a JSON configuration file."""
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Configuration file must contain a JSON object")

    config: Dict[str, ModelConfig] = {}
    for model_name, entry in raw.items():
        if model_name not in model_registry:
            raise KeyError(f"Unknown model '{model_name}' in configuration")
        if entry in (None, "", []):
            config[model_name] = ModelConfig(path=None, columns={})
            continue
        if isinstance(entry, str):
            config[model_name] = ModelConfig(path=Path(entry).expanduser(), columns={})
            continue
        if not isinstance(entry, dict):
            raise ValueError(
                f"Configuration value for '{model_name}' must be a string, object, or null"
            )
        raw_path = entry.get("path")
        columns = entry.get("columns", {})
        if raw_path in (None, "", []):
            path = None
        else:
            path = Path(str(raw_path)).expanduser()
        if not isinstance(columns, Mapping):
            raise ValueError(
                f"Configuration value for '{model_name}.columns' must be an object"
            )
        normalized_columns: Dict[str, str] = {}
        for key, value in columns.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(
                    f"Configuration value for '{model_name}.columns' "
                    "must map strings to strings"
                )
            normalized_columns[key] = value
        config[model_name] = ModelConfig(path=path, columns=normalized_columns)
    return config


def _list_fields(spec: ModelSpec) -> Dict[str, str]:
    model_fields = getattr(spec.model, "model_fields", None)
    if model_fields is None:
        model_fields = getattr(spec.model, "__fields__", {})
    if isinstance(model_fields, dict):
        field_names = list(model_fields.keys())
    else:
        field_names = []
    return {field_name: field_name for field_name in field_names}


def generate_stub_config(
    model_registry: Mapping[str, ModelSpec],
) -> Dict[str, Dict[str, object]]:
    """Create a stub configuration with empty paths and identity column maps for each model."""
    stub: Dict[str, Dict[str, object]] = {}
    for model_name in sorted(model_registry):
        spec = model_registry[model_name]
        stub[model_name] = {
            "path": "",
            "columns": _list_fields(spec),
        }
    return stub
