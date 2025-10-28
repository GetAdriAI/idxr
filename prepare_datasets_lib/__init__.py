"""Helper package for prepare_datasets CLI."""

from .config import (
    DEFAULT_CONFIG_OUTPUT_DIR,
    DEFAULT_CONFIG_TIMESTAMP_FORMAT,
    DropModelConfig,
    PrepModelConfig,
    generate_config_stub,
    get_model_schema_signature,
    load_drop_config,
    load_prep_config,
    slugify_name,
)
from .manifest import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ROW_DIGEST_DELIMITER,
    compute_row_digest,
    load_existing_hashes,
    load_manifest,
    save_manifest,
)
from .partitions import write_partitions
from .drop import generate_drop_config, apply_drop_manifest
from .cli import (
    main,
    handle_new_config,
    handle_run,
    handle_plan_drop,
    handle_apply_drop,
)

__all__ = [
    "DEFAULT_CONFIG_OUTPUT_DIR",
    "DEFAULT_CONFIG_TIMESTAMP_FORMAT",
    "PrepModelConfig",
    "DropModelConfig",
    "generate_config_stub",
    "get_model_schema_signature",
    "load_prep_config",
    "load_drop_config",
    "slugify_name",
    "MANIFEST_FILENAME",
    "MANIFEST_VERSION",
    "ROW_DIGEST_DELIMITER",
    "compute_row_digest",
    "load_existing_hashes",
    "load_manifest",
    "save_manifest",
    "write_partitions",
    "generate_drop_config",
    "apply_drop_manifest",
    "handle_new_config",
    "handle_run",
    "handle_plan_drop",
    "handle_apply_drop",
    "main",
]
