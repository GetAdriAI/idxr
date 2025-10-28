"""Partition writing and CSV sanitisation for prepare_datasets."""

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    DefaultDict,
    Dict,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    TextIO,
    Tuple,
    cast,
)

from indexer.vectorize_lib import format_int
from ..models import ModelSpec

from .config import PrepModelConfig, get_model_schema_signature
from .manifest import (
    compute_row_digest,
    load_existing_hashes,
    load_manifest,
    save_manifest,
)


class PartitionWriter:
    """Helper that manages partition lifecycle during preprocessing."""

    def __init__(
        self,
        *,
        output_root: Path,
        directory_size: int,
        starting_index: int,
        schema_entries: Dict[str, Dict[str, Any]],
    ) -> None:
        self.output_root = output_root
        self.directory_size = max(0, int(directory_size))
        self.partition_index = starting_index
        self.schema_entries = schema_entries

        self.current_partition: Optional[Dict[str, Any]] = None
        self.active_handles: Dict[Tuple[str, str], Any] = {}
        self.active_writers: Dict[Tuple[str, str], Any] = {}
        self.header_written: Dict[Tuple[str, str], bool] = {}
        self.digest_handles: Dict[Tuple[str, str], TextIO] = {}
        self.digest_paths: Dict[Tuple[str, str], Path] = {}
        self.created_partitions: List[Dict[str, Any]] = []
        self.partition_replacements: DefaultDict[str, Set[str]] = defaultdict(set)
        self.context_partition: Optional[str] = None

    def _start_partition(self) -> None:
        name = f"partition_{self.partition_index:05d}"
        self.partition_index += 1
        directory = self.output_root / name
        directory.mkdir(parents=True, exist_ok=True)
        self.current_partition = {
            "name": name,
            "dir": directory,
            "config_entries": {},
            "model_counts": defaultdict(int),
            "model_paths": {},
            "schema": {},
            "rows": 0,
            "replaces": set(),
        }
        if self.context_partition:
            self.current_partition["replaces"].add(self.context_partition)
            self.partition_replacements[self.context_partition].add(name)

    def _close_handles_for(self, partition_name: str) -> None:
        keys = [key for key in self.active_handles if key[0] == partition_name]
        for key in keys:
            handle = self.active_handles.pop(key)
            try:
                handle.close()
            except OSError:
                pass
            self.active_writers.pop(key, None)
            self.header_written.pop(key, None)
            digest_handle = self.digest_handles.pop(key, None)
            if digest_handle is not None:
                try:
                    digest_handle.close()
                except OSError:
                    pass
            self.digest_paths.pop(key, None)

    def finalize_current(self) -> None:
        if self.current_partition is None:
            return
        partition = self.current_partition
        self._close_handles_for(partition["name"])
        if partition["rows"] == 0:
            try:
                partition["dir"].rmdir()
            except OSError:
                pass
            self.current_partition = None
            return

        config_path = partition["dir"] / "vectorize_config.json"
        config_path.write_text(
            json.dumps(partition["config_entries"], indent=2),
            encoding="utf-8",
        )

        models: Dict[str, Dict[str, Any]] = {}
        for model_name, count in partition["model_counts"].items():
            schema_info = partition["schema"].get(model_name, {})
            models[model_name] = {
                "path": str(Path(partition["model_paths"][model_name]).resolve()),
                "rows": int(count),
                "schema_signature": schema_info.get("schema_signature"),
                "schema_version": schema_info.get("schema_version"),
            }

        record = {
            "name": partition["name"],
            "path": str(partition["dir"].resolve()),
            "config": str(config_path.resolve()),
            "rows": int(partition["rows"]),
            "models": models,
            "stale": False,
            "replaces": sorted(partition["replaces"]),
        }
        self.created_partitions.append(record)
        logging.info(
            "Wrote %s with %s row(s) across %s model(s)",
            partition["name"],
            format_int(partition["rows"]),
            format_int(len(models)),
        )
        self.current_partition = None

    def close_all(self) -> None:
        for handle in list(self.active_handles.values()):
            try:
                handle.close()
            except OSError:
                pass
        self.active_handles.clear()
        self.active_writers.clear()
        self.header_written.clear()
        for handle in list(self.digest_handles.values()):
            try:
                handle.close()
            except OSError:
                pass
        self.digest_handles.clear()
        self.digest_paths.clear()

    def set_context(self, partition_name: Optional[str]) -> None:
        self.context_partition = partition_name

    def write_row(
        self,
        *,
        model_name: str,
        headers: Sequence[str],
        row_values: Sequence[str],
    ) -> None:
        if self.current_partition is None or (
            self.directory_size
            and self.current_partition["rows"] >= self.directory_size
        ):
            self.finalize_current()
            self._start_partition()

        partition = self.current_partition
        if partition is None:
            raise RuntimeError("Partition writer failed to initialize partition.")

        handle_key = (partition["name"], model_name)
        writer = self.active_writers.get(handle_key)
        if writer is None:
            out_path = partition["dir"] / f"{model_name}.csv"
            handle = out_path.open("w", encoding="utf-8", newline="")
            writer = csv.writer(handle)
            self.active_writers[handle_key] = writer
            self.active_handles[handle_key] = handle
            self.header_written[handle_key] = False
            partition["model_paths"][model_name] = out_path
            partition["config_entries"][model_name] = {
                "path": str(out_path.resolve()),
                "columns": {},
            }
            digest_path = out_path.with_suffix(out_path.suffix + ".digests")
            digest_path.parent.mkdir(parents=True, exist_ok=True)
            digest_handle = digest_path.open("w", encoding="utf-8")
            self.digest_handles[handle_key] = digest_handle
            self.digest_paths[handle_key] = digest_path
            partition["config_entries"][model_name]["digests"] = str(
                digest_path.resolve()
            )
        else:
            digest_handle = self.digest_handles.get(handle_key)
            if digest_handle is None:
                digest_path = self.digest_paths.get(handle_key)
                if digest_path is None:
                    out_path = partition["model_paths"][model_name]
                    digest_path = out_path.with_suffix(out_path.suffix + ".digests")
                    digest_path.parent.mkdir(parents=True, exist_ok=True)
                    digest_handle = digest_path.open("a", encoding="utf-8")
                    self.digest_paths[handle_key] = digest_path
                else:
                    digest_handle = digest_path.open("a", encoding="utf-8")
                self.digest_handles[handle_key] = digest_handle

        if not headers:
            raise ValueError(f"No headers available for model {model_name}")

        if not self.header_written.get(handle_key, False):
            writer.writerow(list(headers))
            self.header_written[handle_key] = True

        writer.writerow(list(row_values))
        digest = compute_row_digest(row_values)
        digest_handle = self.digest_handles.get(handle_key)
        if digest_handle is not None:
            digest_handle.write(f"{digest}\n")

        schema_entry = self.schema_entries.get(model_name, {})
        partition["schema"][model_name] = {
            "schema_signature": schema_entry.get("signature"),
            "schema_version": schema_entry.get("version"),
        }
        partition["model_counts"][model_name] += 1
        partition["rows"] += 1


def discover_source_files(template_path: Path) -> List[Path]:
    """Return a lexicographically ordered list of files backing the template path."""
    template_str = str(template_path)
    if "<int>" not in template_str:
        if not template_path.exists():
            raise FileNotFoundError(f"Source file {template_path} does not exist")
        return [template_path]

    directory = template_path.parent
    if not directory.exists():
        raise FileNotFoundError(
            f"Directory {directory} referenced by {template_path} does not exist"
        )
    prefix, suffix = template_path.name.split("<int>")
    candidates: List[Tuple[int, Path]] = []
    for candidate in directory.iterdir():
        name = candidate.name
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        middle = name[len(prefix) : len(name) - len(suffix)]
        if middle.isdigit():
            candidates.append((int(middle), candidate))
    if not candidates:
        raise FileNotFoundError(
            f"No files matching template '{template_path}' were found in {directory}"
        )
    candidates.sort(key=lambda item: item[0])
    return [path for _, path in candidates]


def fix_malformed_values(
    values: List[str],
    expected_columns: Optional[int],
    malformed_column: Optional[int],
    delimiter: str,
) -> List[str]:
    """Recombine tokens around a malformed column when extra delimiters appear."""
    if (
        expected_columns is None
        or malformed_column is None
        or expected_columns <= 0
        or len(values) <= expected_columns
    ):
        return values

    target_index = max(0, min(expected_columns - 1, malformed_column - 1))
    leading_count = target_index
    trailing_count = max(0, expected_columns - target_index - 1)

    leading = values[:leading_count]
    trailing = values[-trailing_count:] if trailing_count else []
    middle = values[len(leading) : len(values) - len(trailing)]
    reconstructed = delimiter.join(middle)
    candidate = leading + [reconstructed] + trailing
    if len(candidate) == expected_columns:
        return candidate
    return values


def stitch_multiline_values(
    initial_values: List[str],
    *,
    expected_columns: int,
    malformed_column: Optional[int],
    delimiter: str,
    row_iter: Iterator[Tuple[int, List[str]]],
) -> Tuple[List[str], List[int]]:
    """Attempt to fold subsequent physical rows into the current logical row."""
    stitched = list(initial_values)
    consumed_rows: List[int] = []

    while len(stitched) < expected_columns:
        next_item = next(row_iter, None)
        if next_item is None:
            break

        next_row_number, extra_values = next_item
        consumed_rows.append(next_row_number)

        if stitched:
            if extra_values:
                stitched[-1] = f"{stitched[-1]}\n{extra_values[0]}"
                if len(extra_values) > 1:
                    stitched.extend(extra_values[1:])
            else:
                stitched[-1] = f"{stitched[-1]}\n"
        else:
            stitched = list(extra_values)

        stitched = fix_malformed_values(
            stitched,
            expected_columns,
            malformed_column,
            delimiter,
        )

        if len(stitched) == expected_columns:
            return stitched, consumed_rows
        if len(stitched) > expected_columns:
            break

    return stitched, consumed_rows


def iterate_model_rows(
    config: PrepModelConfig,
    model_name: str,
) -> Iterator[Dict[str, Optional[str]]]:
    """Yield dictionaries keyed by source column name for the target model."""
    if config.path is None:
        return

    source_files = discover_source_files(config.path)
    source_headers: Optional[List[str]] = None
    expected_columns: Optional[int] = None

    for file_index, csv_path in enumerate(source_files):
        has_header = config.header_row == "all" or (
            config.header_row == "first-only" and file_index == 0
        )
        with csv_path.open(
            "r",
            encoding=config.character_encoding,
            errors="replace",
            newline="",
        ) as handle:
            reader = csv.reader(handle, delimiter=config.delimiter)
            row_iter = enumerate(reader, start=1)
            for row_number, values in row_iter:
                if source_headers is None and has_header:
                    source_headers = [
                        value.strip() if isinstance(value, str) else value
                        for value in values
                    ]
                    expected_columns = len(source_headers)
                    continue

                if source_headers is None:
                    if config.columns:
                        source_headers = [
                            config.columns[field] for field in config.columns
                        ]
                        expected_columns = len(source_headers)
                    else:
                        expected_columns = len(values)
                        source_headers = [
                            f"column_{idx+1}" for idx in range(expected_columns)
                        ]

                if has_header and row_number == 1:
                    continue

                if expected_columns is None:
                    expected_columns = len(values)
                if len(values) != expected_columns:
                    values = fix_malformed_values(
                        list(values),
                        expected_columns,
                        config.malformed_column,
                        config.delimiter,
                    )
                if (
                    expected_columns is not None
                    and len(values) < expected_columns
                    and expected_columns > 0
                ):
                    stitched_values, consumed_rows = stitch_multiline_values(
                        list(values),
                        expected_columns=expected_columns,
                        malformed_column=config.malformed_column,
                        delimiter=config.delimiter,
                        row_iter=row_iter,
                    )
                    if len(stitched_values) == expected_columns:
                        values = stitched_values
                    else:
                        last_row = consumed_rows[-1] if consumed_rows else row_number
                        logging.warning(
                            "Skipping %s row %s (spanning up to row %s): "
                            "expected %s column(s), found %s",
                            csv_path,
                            format_int(row_number),
                            format_int(last_row),
                            expected_columns,
                            len(stitched_values),
                        )
                        continue
                if len(values) != expected_columns:
                    logging.warning(
                        "Skipping %s row %s: expected %s column(s), found %s",
                        csv_path,
                        format_int(row_number),
                        expected_columns,
                        len(values),
                    )
                    continue

                row_dict: Dict[str, Optional[str]] = {}
                for idx, header in enumerate(source_headers):
                    value: Optional[str]
                    if idx < len(values):
                        cell = values[idx]
                        if isinstance(cell, str):
                            value = cell.strip()
                        else:
                            value = str(cell) if cell is not None else None
                    else:
                        value = None
                    row_dict[header] = value
                yield row_dict


def sanitize_row(
    row: MutableMapping[str, Optional[str]],
    config: PrepModelConfig,
) -> Optional[Dict[str, Optional[str]]]:
    """Project a raw row onto the requested columns and drop invalid entries."""
    if config.columns:
        final_row = {
            target: row.get(source) for target, source in config.columns.items()
        }
    else:
        final_row = dict(row)

    for drop_field in config.drop_na_columns:
        if final_row.get(drop_field) in (None, "", "NA", "N/A"):
            return None
    return final_row


def write_partitions(
    output_root: Path,
    directory_size: int,
    configs: Dict[str, PrepModelConfig],
    manifest_path: Path,
    run_id: str,
    source_config_path: Path,
    *,
    model_registry: Mapping[str, ModelSpec],
) -> None:
    """Create or append partition directories and update the manifest for incremental runs."""
    manifest = load_manifest(manifest_path)
    seen_hashes = load_existing_hashes(manifest)

    # Ensure hash sets exist for models we touch later.
    for model_name in list(seen_hashes.keys()):
        seen_hashes.setdefault(model_name, set())

    partitions: List[Dict[str, Any]] = [
        entry for entry in manifest.get("partitions", []) if isinstance(entry, dict)
    ]
    existing_model_schemas: Dict[str, Dict[str, Any]] = manifest.setdefault(
        "model_schemas", {}
    )

    models_in_manifest: Set[str] = set()
    for entry in partitions:
        models_in_manifest.update(entry.get("models", {}).keys())

    models_to_consider: Set[str] = set(configs.keys()) | models_in_manifest

    current_signatures: Dict[str, str] = {
        model_name: get_model_schema_signature(
            model_name, model_registry=model_registry
        )
        for model_name in models_to_consider
    }

    new_schema_entries: Dict[str, Dict[str, Any]] = {}
    modified_models: Set[str] = set()
    for model_name, signature in current_signatures.items():
        previous = existing_model_schemas.get(model_name)
        if previous and previous.get("signature") != signature:
            modified_models.add(model_name)
            version = int(previous.get("version", 1)) + 1
        elif previous:
            version = int(previous.get("version", 1))
        else:
            version = 1
        new_schema_entries[model_name] = {"signature": signature, "version": version}

    missing_modified_sources = [
        model
        for model in sorted(modified_models)
        if model not in configs or configs[model].path is None
    ]
    if missing_modified_sources:
        logging.error(
            "Detected schema changes for %s but no source CSV is configured.",
            ", ".join(missing_modified_sources),
        )
        return

    impacted_partitions: List[Dict[str, Any]] = []
    impacted_partition_names: List[str] = []
    for entry in partitions:
        if entry.get("stale"):
            continue
        models = entry.get("models", {})
        if any(model in modified_models for model in models.keys()):
            impacted_partitions.append(entry)
            impacted_partition_names.append(entry.get("name", ""))

    carryover_by_partition: Dict[str, Dict[str, Dict[str, Any]]] = {}
    carryover_headers: Dict[str, List[str]] = {}
    for entry in impacted_partitions:
        partition_name = entry.get("name")
        if not partition_name:
            continue
        models = entry.get("models", {})
        copied: Dict[str, Dict[str, Any]] = {}
        for model_name, model_info in models.items():
            if model_name in modified_models:
                continue
            csv_path = Path(str(model_info.get("path", "")))
            if not csv_path.exists():
                logging.warning(
                    "Unable to copy %s from stale partition %s: %s missing.",
                    model_name,
                    partition_name,
                    csv_path,
                )
                continue
            try:
                with csv_path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.reader(handle)
                    headers = next(reader, None) or []
                    if not headers:
                        continue
                    rows: List[List[str]] = [row for row in reader]
            except (OSError, csv.Error) as exc:
                logging.warning(
                    "Skipping carryover for %s from %s (%s)",
                    model_name,
                    partition_name,
                    exc,
                )
                continue
            if not rows:
                continue
            carryover_headers.setdefault(model_name, headers)
            copied[model_name] = {"headers": headers, "rows": rows}
            hashes = seen_hashes.setdefault(model_name, set())
            for row in rows:
                hashes.add(compute_row_digest(row))
        if copied:
            carryover_by_partition[partition_name] = copied

    for model_name in models_to_consider:
        seen_hashes.setdefault(model_name, set())
    model_names = sorted(set(models_to_consider) | set(carryover_headers.keys()))

    final_headers: Dict[str, List[str]] = {}
    for model_name in model_names:
        header = carryover_headers.get(model_name)
        if header:
            final_headers[model_name] = list(header)
        else:
            cfg = configs.get(model_name)
            if cfg and cfg.columns:
                final_headers[model_name] = list(cfg.columns.keys())
            else:
                final_headers[model_name] = []

    partition_writer = PartitionWriter(
        output_root=output_root,
        directory_size=directory_size,
        starting_index=len(partitions),
        schema_entries=new_schema_entries,
    )

    try:
        # Step 1 & 2: copy unaffected models from impacted partitions.
        for entry in impacted_partitions:
            partition_name = entry.get("name")
            if not partition_name:
                continue
            carryover_models = carryover_by_partition.get(partition_name, {})
            if not carryover_models:
                continue
            logging.info(
                "Rehydrating unaffected models for stale partition %s",
                partition_name,
            )
            partition_writer.set_context(partition_name)
            for model_name, payload in carryover_models.items():
                raw_headers = payload.get("headers")
                rows = payload.get("rows", [])
                if not isinstance(raw_headers, list) or not rows:
                    continue
                header_list = [str(item) for item in raw_headers]
                final_headers[model_name] = list(header_list)
                hashes = seen_hashes.setdefault(model_name, set())
                for row in rows:
                    partition_writer.write_row(
                        model_name=model_name,
                        headers=header_list,
                        row_values=row,
                    )
                    hashes.add(compute_row_digest(row))
            partition_writer.set_context(None)

        # Step 3: stream new/updated rows from configured CSVs.
        for model_name in model_names:
            cfg = configs.get(model_name)
            if cfg is None or cfg.path is None:
                continue
            logging.info("Processing model %s from %s", model_name, cfg.path)
            hashes = seen_hashes.setdefault(model_name, set())
            for raw_row in iterate_model_rows(cfg, model_name):
                sanitized = sanitize_row(raw_row, cfg)
                if sanitized is None:
                    continue
                headers = final_headers.get(model_name, [])
                if not headers:
                    headers = list(sanitized.keys())
                    final_headers[model_name] = headers
                headers = cast(List[str], headers)
                row_values: List[str] = []
                for column in headers:
                    value = sanitized.get(column)
                    row_values.append("" if value is None else str(value))
                digest = compute_row_digest(row_values)
                if digest in hashes:
                    continue
                hashes.add(digest)
                partition_writer.write_row(
                    model_name=model_name,
                    headers=headers,
                    row_values=row_values,
                )

    finally:
        partition_writer.finalize_current()
        partition_writer.close_all()

    created_partitions = partition_writer.created_partitions
    if not created_partitions:
        if modified_models:
            logging.warning(
                "Schema changes detected (%s) but no new partitions were created.",
                ", ".join(sorted(modified_models)),
            )
        else:
            logging.info("No new rows detected; manifest remains unchanged.")
        return

    timestamp = (
        datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    )
    for record in created_partitions:
        record["created_at"] = timestamp
        record["run_id"] = run_id

    manifest.setdefault("partitions", [])
    manifest["partitions"].extend(created_partitions)
    manifest.setdefault("runs", [])
    manifest["runs"].append(
        {
            "id": run_id,
            "config_path": str(source_config_path),
            "created_at": timestamp,
            "partitions": [record["name"] for record in created_partitions],
        }
    )

    # Update schema registry.
    for model_name, entry in new_schema_entries.items():
        manifest["model_schemas"][model_name] = {
            "signature": entry["signature"],
            "version": entry["version"],
        }

    # Mark impacted partitions as stale.
    if impacted_partition_names:
        replacements_map = partition_writer.partition_replacements
        for entry in partitions:
            name = entry.get("name")
            if not name or name not in impacted_partition_names:
                continue
            if entry.get("stale"):
                continue
            entry["stale"] = True
            entry["stale_reason"] = "schema-change"
            entry["stale_at"] = timestamp
            new_names = sorted(replacements_map.get(name, set()))
            if new_names:
                entry["replaced_by"] = sorted(
                    set(entry.get("replaced_by", [])) | set(new_names)
                )

    save_manifest(manifest_path, manifest)
    logging.info(
        "Recorded %s new partition(s) in manifest %s",
        format_int(len(created_partitions)),
        manifest_path,
    )
