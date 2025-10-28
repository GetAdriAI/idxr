"""Generic helpers for vectorize."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from chromadb.api import Collection


TOKEN_SAFETY_LIMIT = 250_000
MAX_TOKENS_PER_REQUEST = 300_000
TOKEN_BUFFER = MAX_TOKENS_PER_REQUEST - TOKEN_SAFETY_LIMIT
MAX_DOCS_PER_REQUEST = 2_048


def format_int(value: int) -> str:
    """Return human-friendly representation for integers with thousands separators."""
    return f"{value:,}"


@lru_cache(maxsize=8)
def get_token_encoder(model_name: str):
    """Return a cached tiktoken encoder for the requested model."""
    try:
        import tiktoken
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "Token counting requires the 'tiktoken' package. "
            "Install it via 'pip install tiktoken'."
        ) from exc

    try:
        return tiktoken.encoding_for_model(model_name)
    except KeyError:
        logging.warning(
            "No dedicated tokenizer found for %s; falling back to cl100k_base.",
            model_name,
        )
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, encoder: Any) -> int:
    """Return token count for a string using the provided encoder."""
    if not text:
        return 0
    return len(encoder.encode(text))


def load_completion_state(path: Optional[Path]) -> Dict[str, Any]:
    """Load the per-model completion metadata if available."""
    if path is None:
        return {}
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
        logging.warning(
            "Completion metadata at %s is not a JSON object; ignoring.",
            path,
        )
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Failed to read completion metadata at %s: %s", path, exc)
    return {}


def get_path_signature(path: Path) -> Optional[Dict[str, float]]:
    """Return a simple fingerprint for the file so we can detect changes."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"mtime": stat.st_mtime, "size": stat.st_size}


def summarize_collection(
    collection: Collection,
    chunk_size: int,
    log_progress: bool = False,
) -> Tuple[int, Dict[str, int], int]:
    """Return total count, per-model counts, and missing-metadata count for a collection."""
    total = collection.count()
    counts: Dict[str, int] = {}
    missing = 0
    if total == 0:
        return total, counts, missing

    offset = 0
    while offset < total:
        batch = collection.get(
            include=["metadatas"],
            limit=chunk_size,
            offset=offset,
        )
        ids = batch.get("ids") or []
        metadatas = batch.get("metadatas") or []
        if not ids:
            break

        for metadata in metadatas:
            model_name: Optional[str] = None
            if isinstance(metadata, Mapping):
                raw_model_name = metadata.get("model_name")
                if isinstance(raw_model_name, str):
                    model_name = raw_model_name
            if model_name:
                counts[model_name] = counts.get(model_name, 0) + 1
            else:
                missing += 1

        offset += len(ids)
        if log_progress:
            percent = (offset / total) * 100 if total else 100.0
            logging.info(
                "Scanned %d/%d documents (%.2f%%)",
                offset,
                total,
                percent,
            )
        if len(ids) < chunk_size:
            break

    return total, counts, missing
