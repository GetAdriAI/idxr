"""Logging configuration with file rotation support for large-scale indexing operations."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    max_bytes: int = 100 * 1024 * 1024,  # 100 MB per file
    backup_count: int = 10,  # Keep 10 backup files
    console_output: bool = True,
) -> None:
    """Configure logging with optional file rotation for large-scale operations.

    This function sets up logging to handle millions of records with automatic
    log rotation to prevent disk space issues. By default, it creates 100MB log
    files and keeps 10 backups (1GB total).

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to the log file. If None, only console logging is used.
        max_bytes: Maximum size of a single log file before rotation (default: 100MB)
        backup_count: Number of backup files to keep (default: 10)
        console_output: Whether to also output logs to console (default: True)

    Examples:
        # Console only (default behavior)
        setup_logging(log_level="INFO")

        # File logging with rotation
        setup_logging(
            log_level="INFO",
            log_file=Path("logs/vectorize.log"),
            max_bytes=100 * 1024 * 1024,  # 100 MB
            backup_count=10,  # Keep 10 backups
        )

        # File only (no console output)
        setup_logging(
            log_level="INFO",
            log_file=Path("logs/vectorize.log"),
            console_output=False,
        )
    """
    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: List[logging.Handler] = []

    # Add console handler if requested
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    # Add file handler with rotation if log_file is specified
    if log_file:
        # Ensure the log directory exists
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

        logging.info(
            "File logging enabled: %s (max_bytes=%s, backup_count=%d)",
            log_file,
            _format_bytes(max_bytes),
            backup_count,
        )

    # Add all handlers to root logger
    for handler in handlers:
        root_logger.addHandler(handler)


def _format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable string.

    Args:
        num_bytes: Number of bytes

    Returns:
        Human-readable string (e.g., "100.0 MB")
    """
    bytes_float = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_float < 1024.0:
            return f"{bytes_float:.1f} {unit}"
        bytes_float /= 1024.0
    return f"{bytes_float:.1f} PB"
