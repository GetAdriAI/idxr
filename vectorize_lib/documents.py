"""Document serialization and CSV streaming utilities."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Tuple,
    Union,
    cast,
)

from pydantic import BaseModel, ValidationError

from indexer.models import ModelSpec
from .utils import format_int

MetadataValue = Union[str, int, float, bool, None]
MetadataDict = Dict[str, MetadataValue]


@dataclass
class ResumeState:
    """Tracks CSV stream position so resume runs can seek directly to new rows."""

    offset: Optional[int] = None
    row_index: int = 0
    fieldnames: Optional[List[str]] = None


def model_to_dict(instance: BaseModel) -> Dict[str, Any]:
    """Convert a Pydantic model into a plain dict for serialization."""
    return instance.model_dump()


def build_document_id(model_name: str, instance: BaseModel) -> str:
    """Generate a deterministic identifier for a document."""
    payload = model_to_dict(instance)
    canonical = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    return f"{model_name}:{digest}"


def build_semantic_text(instance: BaseModel, spec: ModelSpec) -> str:
    """Create the textual content used for semantic embedding."""
    values: List[str] = []
    for field in spec.semantic_fields:
        value = getattr(instance, field, None)
        if value not in (None, "", [], {}):
            values.append(str(value))
    if values:
        return "\n".join(values)
    return json.dumps(model_to_dict(instance), sort_keys=True, default=str)


def build_metadata(
    instance: BaseModel,
    spec: ModelSpec,
    model_name: str,
    source_path: Path,
    extra_metadata: Optional[Mapping[str, MetadataValue]] = None,
    schema_version: Optional[int] = None,
) -> MetadataDict:
    """Create metadata dict for ChromaDB."""
    metadata: MetadataDict = {
        "model_name": model_name,
        "source_path": str(source_path),
    }
    if schema_version is not None:
        metadata["schema_version"] = int(schema_version)
    for field in spec.keyword_fields:
        value = getattr(instance, field, None)
        if value not in (None, "", [], {}):
            metadata[field] = cast(MetadataValue, value)
    if extra_metadata:
        for key, value in extra_metadata.items():
            metadata[str(key)] = cast(MetadataValue, value)
    return metadata


def remap_row(
    row: MutableMapping[str, Any], column_map: Mapping[str, str]
) -> Dict[str, Any]:
    """Return a copy of the CSV row with columns renamed to model field names."""
    if not column_map:
        return dict(row)
    remapped: Dict[str, Any] = dict(row)
    for target_field, source_column in column_map.items():
        remapped[target_field] = remapped.get(source_column)
    return remapped


def normalize_row(row: MutableMapping[str, Any]) -> Dict[str, Any]:
    """Replace empty strings with None to help Pydantic parse optional fields."""
    normalized: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, str):
            normalized[key] = value.strip() if value.strip() else None
        else:
            normalized[key] = value
    return normalized


def iter_documents(
    model_name: str,
    csv_path: Path,
    spec: ModelSpec,
    column_map: Mapping[str, str],
    skip: int = 0,
    resume_state: Optional[ResumeState] = None,
    on_skip_complete: Optional[Callable[[ResumeState], None]] = None,
    extra_metadata: Optional[Mapping[str, MetadataValue]] = None,
    schema_version: Optional[int] = None,
) -> Iterator[Tuple[int, str, str, MetadataDict]]:
    """Yield document payloads (row index, id, text, metadata) for a given model CSV."""

    start_offset: Optional[int] = None
    start_row_index = 0
    fieldnames_override: Optional[List[str]] = None
    if resume_state:
        if isinstance(resume_state.offset, int) and resume_state.offset >= 0:
            start_offset = resume_state.offset
        start_row_index = max(0, int(resume_state.row_index))
        if resume_state.fieldnames:
            fieldnames_override = list(resume_state.fieldnames)

    effective_skip = max(0, skip)
    with csv_path.open("rb") as raw_handle:
        if start_offset is not None:
            try:
                raw_handle.seek(start_offset)
            except OSError as exc:
                logging.warning(
                    "Failed to seek %s to stored offset %s (%s); restarting from beginning.",
                    csv_path,
                    format_int(start_offset),
                    exc,
                )
                raw_handle.seek(0)
                start_offset = None
                start_row_index = 0
                fieldnames_override = None
                effective_skip = max(0, skip)
                if resume_state:
                    resume_state.offset = None
                    resume_state.row_index = 0
                    resume_state.fieldnames = None

        text_handle = io.TextIOWrapper(raw_handle, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text_handle, fieldnames=fieldnames_override)
        actual_fieldnames = list(reader.fieldnames or [])
        if not actual_fieldnames:
            logging.warning("Skipped %s: no header found", csv_path)
            return
        if resume_state:
            resume_state.fieldnames = actual_fieldnames

        if start_offset is not None:
            effective_skip = 0
            starting_row = start_row_index + 1
        else:
            starting_row = 1

        skip_notified = False

        for row_index, row in enumerate(reader, start=starting_row):
            if resume_state:
                try:
                    resume_state.offset = raw_handle.tell()
                except OSError:
                    resume_state.offset = None
                resume_state.row_index = row_index

            if effective_skip and row_index <= effective_skip:
                if (
                    not skip_notified
                    and row_index >= effective_skip
                    and on_skip_complete
                    and resume_state
                ):
                    on_skip_complete(resume_state)
                    skip_notified = True
                continue

            remapped = remap_row(row, column_map)
            normalized = normalize_row(remapped)
            try:
                instance = spec.model(**normalized)
            except ValidationError as exc:
                logging.warning(
                    "Skipping %s row %d due to validation error: %s",
                    csv_path,
                    row_index,
                    exc.errors(),
                )
                continue
            doc_id = build_document_id(model_name, instance)
            document_text = build_semantic_text(instance, spec)
            metadata = build_metadata(
                instance,
                spec,
                model_name,
                csv_path,
                extra_metadata=extra_metadata,
                schema_version=schema_version,
            )
            yield row_index, doc_id, document_text, metadata
