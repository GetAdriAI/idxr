"""Command-line entry points for prepare_datasets."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from indexer.load_model_registry import load_model_registry
from indexer.vectorize_lib.utils import format_int

from .config import (
    DEFAULT_CONFIG_OUTPUT_DIR,
    DEFAULT_CONFIG_TIMESTAMP_FORMAT,
    load_drop_config,
    generate_config_stub,
    load_prep_config,
    slugify_name,
)
from .manifest import MANIFEST_FILENAME
from .partitions import write_partitions
from .drop import generate_drop_config, apply_drop_manifest


def handle_new_config(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="prepare_datasets.py new-config",
        description="Scaffold a prepare_datasets configuration stub with "
        "optional model filtering.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples
            --------
            prepare_datasets.py new-config full_export \\
                --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY
            prepare_datasets.py new-config hotfix \\
                --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \\
                --models Table,Field \\
                --output-dir workdir/prepare_datasets/configs
            """
        ),
    )
    parser.add_argument(
        "name",
        help="Human-friendly identifier for this config stub (used in the filename slug).",
    )
    parser.add_argument(
        "--model",
        required=True,
        help=(
            "Python import string for the model registry "
            "(format: package.module:REGISTRY_NAME)."
        ),
    )
    parser.add_argument(
        "--models",
        help="Comma-separated list of model names to include "
        "(defaults to all registered models).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_CONFIG_OUTPUT_DIR,
        help=(
            "Directory where the stub will be written "
            f"(defaults to ./{DEFAULT_CONFIG_OUTPUT_DIR})."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.",
    )

    args = parser.parse_args(list(argv))
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    try:
        model_registry = load_model_registry(str(args.model))
    except (TypeError, ValueError) as exc:
        logging.error("Failed to load model registry %s: %s", args.model, exc)
        return 1

    if args.models:
        requested = [item.strip() for item in args.models.split(",") if item.strip()]
        missing = [model for model in requested if model not in model_registry]
        if missing:
            parser.error(
                f"Unknown model(s): {', '.join(missing)}. "
                f"Valid options: {', '.join(sorted(model_registry))}"
            )
        model_list = requested
    else:
        model_list = sorted(model_registry)

    if not model_list:
        logging.error("No models specified; nothing to scaffold.")
        return 1

    slug = slugify_name(args.name)
    timestamp = datetime.utcnow().strftime(DEFAULT_CONFIG_TIMESTAMP_FORMAT)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = f"{timestamp}_{slug}.json"
    output_path = output_dir / base_name
    counter = 1
    while output_path.exists():
        output_path = output_dir / f"{timestamp}_{slug}_{counter:02d}.json"
        counter += 1

    stub = generate_config_stub(model_list, model_registry=model_registry)
    output_path.write_text(json.dumps(stub, indent=2), encoding="utf-8")

    logging.info(
        "Wrote prepare_datasets config stub for %s model(s) at %s",
        format_int(len(model_list)),
        output_path,
    )
    return 0


def handle_run(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="prepare_datasets.py",
        description=textwrap.dedent(
            """
            Partition, sanitize, and de-duplicate SAP CSV exports ahead
            of vectorize.py ingestion.

            Each run appends new partition directories to a manifest so multiple configs layer
            together like migrations. Previously processed rows are skipped automatically
            based on row digests stored in the manifest.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Example workflows
            -----------------
            prepare_datasets.py \\
                --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \\
                --config configs/full_export.json --output-root build/partitions

            prepare_datasets.py \\
                --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \\
                --config configs/hotfix.csv.json --output-root build/partitions \\
                --manifest build/partitions/manifest.json

            prepare_datasets.py new-config hotfix \\
                --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \\
                --models Table,Field
            """
        ),
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the preprocessing JSON configuration "
        "(same structure as vectorize config with extras).",
    )
    parser.add_argument(
        "--model",
        required=True,
        help=(
            "Python import string for the model registry "
            "(format: package.module:REGISTRY_NAME)."
        ),
    )
    parser.add_argument(
        "--output-root",
        required=True,
        type=Path,
        help="Destination directory where partition subdirectories will be created.",
    )
    parser.add_argument(
        "--directory-size",
        type=int,
        default=0,
        help="Maximum number of rows per model per partition directory (0 means unlimited).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help=(
            "Path to the manifest JSON file (defaults to <output-root>/manifest.json). "
            "Reuse the same manifest across runs to accumulate incremental "
            "'migration' datasets."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.",
    )

    args = parser.parse_args(list(argv))
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    try:
        model_registry = load_model_registry(str(args.model))
    except (TypeError, ValueError) as exc:
        logging.error("Failed to load model registry %s: %s", args.model, exc)
        return 1

    source_config_path = args.config.resolve()

    try:
        configs = load_prep_config(source_config_path, model_registry=model_registry)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logging.error("Failed to load configuration: %s", exc)
        return 1

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    manifest_path = (
        args.manifest.resolve()
        if args.manifest is not None
        else (output_root / MANIFEST_FILENAME).resolve()
    )
    run_id = uuid.uuid4().hex

    try:
        write_partitions(
            output_root=output_root,
            directory_size=args.directory_size,
            configs=configs,
            manifest_path=manifest_path,
            run_id=run_id,
            source_config_path=source_config_path,
            model_registry=model_registry,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        logging.error("Preprocessing failed: %s", exc)
        return 1

    logging.info("Preprocessing complete.")
    return 0


def handle_plan_drop(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="prepare_datasets.py plan-drop",
        description="Generate a model-centric drop configuration from the manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Example
            -------
            prepare_datasets.py plan-drop \\
                --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \\
                --manifest build/partitions/manifest.json \\
                --models Table,Field --before 2024-07-01 \\
                --output configs/drop/gdpr.json
            """
        ),
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to the manifest JSON file to analyse.",
    )
    parser.add_argument(
        "--models",
        required=True,
        help="Comma-separated list of models to target.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help=(
            "Python import string for the model registry "
            "(format: package.module:REGISTRY_NAME)."
        ),
    )
    parser.add_argument(
        "--before",
        help="Only include partitions created before this "
        "ISO date/time (YYYY-MM-DD or ISO 8601).",
    )
    parser.add_argument(
        "--after",
        help="Only include partitions created on/after this ISO date/time.",
    )
    parser.add_argument(
        "--reason",
        help="Optional default reason recorded in the drop config.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("drop_plan.json"),
        help="Destination file for the generated drop configuration (default: drop_plan.json).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.",
    )

    args = parser.parse_args(list(argv))
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    try:
        model_registry = load_model_registry(str(args.model))
    except (TypeError, ValueError) as exc:
        logging.error("Failed to load model registry %s: %s", args.model, exc)
        return 1

    model_list = [item.strip() for item in args.models.split(",") if item.strip()]
    if not model_list:
        logging.error("No models specified; nothing to plan.")
        return 1

    unknown = [model for model in model_list if model not in model_registry]
    if unknown:
        logging.error("Unknown model(s): %s", ", ".join(unknown))
        return 1

    plan_dict, summaries = generate_drop_config(
        manifest_path=args.manifest.resolve(),
        models=model_list,
        before=args.before,
        after=args.after,
        default_reason=args.reason,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan_dict, indent=2), encoding="utf-8")

    if not summaries:
        logging.warning("No matching partitions found for the requested models.")
        return 0

    logging.info("Generated drop config at %s", args.output)
    for summary in summaries:
        logging.info(
            "Model %s -> %s partition(s)%s",
            summary.model,
            format_int(len(summary.partitions)),
            (
                f" (schema versions {', '.join(str(v) for v in summary.schema_versions)})"
                if summary.schema_versions
                else ""
            ),
        )
    return 0


def handle_apply_drop(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="prepare_datasets.py apply-drop",
        description="Apply a drop configuration to the manifest (and optionally local files).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the drop configuration generated via plan-drop or hand-authored.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Manifest file to update.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag, a dry-run summary is shown.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Remove local CSV files for the affected models (only with --apply).",
    )
    parser.add_argument(
        "--performed-by",
        help="Optional identifier recorded in the manifest audit log.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help=(
            "Python import string for the model registry "
            "(format: package.module:REGISTRY_NAME)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.",
    )

    args = parser.parse_args(list(argv))
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    if args.local and not args.apply:
        logging.warning("--local has no effect unless --apply is set.")

    try:
        model_registry = load_model_registry(str(args.model))
    except (TypeError, ValueError) as exc:
        logging.error("Failed to load model registry %s: %s", args.model, exc)
        return 1

    try:
        drop_configs, _ = load_drop_config(args.config, model_registry=model_registry)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logging.error("Failed to load drop configuration: %s", exc)
        return 1

    if not drop_configs:
        logging.warning("Drop configuration did not include any models.")
        return 0

    results = apply_drop_manifest(
        manifest_path=args.manifest.resolve(),
        drop_config_path=args.config.resolve(),
        apply_changes=args.apply,
        remove_local=args.local,
        performed_by=args.performed_by,
        model_registry=model_registry,
    )

    if not results:
        logging.warning("No matching manifest entries were found for the drop request.")
        return 0

    model_counts: Counter[str] = Counter()
    partition_counts: Counter[str] = Counter()
    for item in results:
        model_counts[item.model] += item.rows
        partition_counts[item.partition] += 1

    for model, total_rows in model_counts.items():
        partition_total = sum(1 for item in results if item.model == model)
        logging.info(
            "%s -> %s partition(s), %s row(s)",
            model,
            format_int(partition_total),
            format_int(total_rows),
        )

    if args.apply:
        logging.info(
            "Applied drop configuration %s to manifest %s",
            args.config,
            args.manifest,
        )
    else:
        logging.info(
            "Dry-run only. Re-run with --apply to persist the manifest changes."
        )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if argv and argv[0] == "new-config":
        return handle_new_config(argv[1:])
    if argv and argv[0] == "plan-drop":
        return handle_plan_drop(argv[1:])
    if argv and argv[0] == "apply-drop":
        return handle_apply_drop(argv[1:])
    return handle_run(argv)
