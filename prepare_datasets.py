"""CLI entry point for prepare_datasets."""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from indexer.prepare_datasets_lib import (
    DEFAULT_CONFIG_OUTPUT_DIR,
    DEFAULT_CONFIG_TIMESTAMP_FORMAT,
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    PrepModelConfig,
    compute_row_digest,
    generate_config_stub,
    handle_new_config,
    handle_run,
    load_existing_hashes,
    load_manifest,
    load_prep_config,
    save_manifest,
    slugify_name,
    write_partitions,
    main as run_main,
)

__all__ = [
    "DEFAULT_CONFIG_OUTPUT_DIR",
    "DEFAULT_CONFIG_TIMESTAMP_FORMAT",
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "PrepModelConfig",
    "compute_row_digest",
    "generate_config_stub",
    "load_existing_hashes",
    "load_manifest",
    "load_prep_config",
    "save_manifest",
    "slugify_name",
    "write_partitions",
    "handle_new_config",
    "handle_run",
    "main",
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the CLI."""
    return run_main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
