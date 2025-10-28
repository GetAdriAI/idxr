"""Validation helpers for vectorize configuration and CSV sources."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Mapping

from pydantic import ValidationError

from .configuration import ModelConfig
from .documents import normalize_row, remap_row
from indexer.models import ModelSpec


def validate_csv_against_model(
    model_name: str,
    csv_path: Path,
    spec: ModelSpec,
    column_map: Mapping[str, str],
) -> bool:
    """Stream the CSV once to ensure headers exist and every row passes Pydantic validation."""
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                logging.error(
                    "Validation failed for %s: no header found in %s",
                    model_name,
                    csv_path,
                )
                return False
            for row_index, row in enumerate(reader, start=1):
                remapped = remap_row(row, column_map)
                normalized = normalize_row(remapped)
                try:
                    spec.model(**normalized)
                except ValidationError as exc:
                    logging.error(
                        "Validation failed for %s: row %d in %s does not conform: %s",
                        model_name,
                        row_index,
                        csv_path,
                        exc.errors(),
                    )
                    return False
    except OSError as exc:
        logging.error(
            "Validation failed for %s: could not open %s (%s)",
            model_name,
            csv_path,
            exc,
        )
        return False
    except csv.Error as exc:
        logging.error(
            "Validation failed for %s: CSV parsing error in %s (%s)",
            model_name,
            csv_path,
            exc,
        )
        return False
    return True


def validate_config_sources(
    config: Dict[str, ModelConfig],
    *,
    model_registry: Mapping[str, ModelSpec],
) -> bool:
    """Validate the existence and schema conformance of configured CSV sources."""
    all_valid = True
    for model_name, model_config in config.items():
        csv_path = model_config.path
        if csv_path is None:
            logging.info(
                "Skipping %s during validation: no CSV path provided", model_name
            )
            continue
        if not csv_path.exists():
            logging.error(
                "Validation failed for %s: CSV path %s does not exist",
                model_name,
                csv_path,
            )
            all_valid = False
            continue
        spec = model_registry[model_name]
        logging.info("Validating %s using %s", model_name, csv_path)
        if not validate_csv_against_model(
            model_name, csv_path, spec, model_config.columns
        ):
            all_valid = False
    return all_valid
