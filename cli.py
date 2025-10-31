"""Primary command-line entry point for idxr.

This module exposes a single ``idxr`` executable with subcommands that
delegate to the existing ``prepare_datasets.py`` and ``vectorize.py`` CLIs.
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Sequence

from indexer.prepare_datasets import main as prepare_datasets_main
from indexer.vectorize import main as vectorize_main

CommandHandler = Callable[[Sequence[str]], int]

COMMANDS: Dict[str, CommandHandler] = {
    "prepare_datasets": prepare_datasets_main,
    "prepare-datasets": prepare_datasets_main,
    "vectorize": vectorize_main,
}

HELP_TEXT = """\
Usage: idxr <command> [<args>]

Commands:
  prepare_datasets   Run the dataset preparation pipeline (alias: prepare-datasets)
  vectorize          Execute the vectorization pipeline

Run `idxr <command> --help` to see the options for a specific command.
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch to the requested subcommand."""
    args: List[str] = list(argv if argv is not None else sys.argv[1:])

    if not args or args[0] in {"-h", "--help", "help"}:
        print(HELP_TEXT)
        return 0

    command = args[0]
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"Unknown command '{command}'.\n", file=sys.stderr)
        print(HELP_TEXT, file=sys.stderr)
        return 1

    return handler(args[1:])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
