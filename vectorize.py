"""CLI entry point for the vectorize pipeline."""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from dotenv import load_dotenv

from indexer.vectorize_lib import (
    ModelConfig,
    VectorizeCLI,
    format_int,
    generate_stub_config,
    load_config,
    main as run_main,
)
from indexer.load_model_registry import load_model_registry
from indexer.models import ModelSpec
from kb.std.ecc_6_0_ehp_7.registry import MODEL_REGISTRY

load_dotenv()

__all__ = [
    "MODEL_REGISTRY",
    "ModelConfig",
    "ModelSpec",
    "VectorizeCLI",
    "format_int",
    "generate_stub_config",
    "load_config",
    "load_model_registry",
    "main",
]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the CLI."""
    return run_main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
