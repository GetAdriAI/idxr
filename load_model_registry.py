"""Model registry for vectorization."""

import importlib
from typing import Dict, Mapping

from .models import ModelSpec


def load_model_registry(target: str) -> Mapping[str, ModelSpec]:
    """Import and validate a model registry specified as ``module:attribute``."""
    if ":" not in target:
        raise ValueError("Model registry must be specified as '<module>:<attribute>'.")
    module_path, attr_path = target.split(":", 1)
    module_path = module_path.strip()
    attr_path = attr_path.strip()
    if not module_path or not attr_path:
        raise ValueError("Both module and attribute must be provided for --model.")

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover - defensive
        raise ValueError(f"Could not import module '{module_path}': {exc}") from exc

    attr_parts = [part for part in attr_path.split(".") if part]
    if not attr_parts:
        raise ValueError("Attribute path after ':' cannot be empty.")

    registry_obj = module
    for part in attr_parts:
        try:
            registry_obj = getattr(registry_obj, part)
        except AttributeError as exc:
            raise ValueError(
                f"Attribute '{attr_path}' not found in module '{module_path}'."
            ) from exc

    if not isinstance(registry_obj, Mapping):
        raise TypeError(
            f"Attribute '{attr_path}' in module '{module_path}' is not a mapping."
        )

    registry: Dict[str, ModelSpec] = {}
    for key, value in registry_obj.items():
        if not isinstance(key, str):
            raise TypeError("Model registry keys must be strings.")
        if not isinstance(value, ModelSpec):
            raise TypeError(
                f"Model registry entry '{key}' is not a ModelSpec instance."
            )
        registry[key] = value
    if not registry:
        raise ValueError("Model registry is empty; no models available.")
    return registry
