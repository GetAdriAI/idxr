"""Indexing pipeline that streams CSV rows into ChromaDB."""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, cast

from chromadb import errors as chroma_errors
from chromadb.api import Collection
from chromadb.utils.embedding_functions import (
    EmbeddingFunction,
    OpenAIEmbeddingFunction,
)

from .configuration import ModelConfig
from .documents import (
    MetadataDict,
    MetadataValue,
    ResumeState,
    iter_documents,
)
from indexer.models import ModelSpec
from .utils import (
    MAX_DOCS_PER_REQUEST,
    MAX_TOKENS_PER_REQUEST,
    TOKEN_SAFETY_LIMIT,
    count_tokens,
    format_int,
    get_path_signature,
    summarize_collection,
)

InvalidCollectionError = cast(
    type[BaseException],
    getattr(
        chroma_errors,
        "InvalidCollectionException",
        getattr(chroma_errors, "InvalidCollectionError", Exception),
    ),
)


def create_embedding_function(
    model_name: str, api_key: Optional[str] = None
) -> EmbeddingFunction[Any]:
    """Factory to create the OpenAI embedding function used by ChromaDB."""
    api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OpenAI API key is required (use --openai-api-key or set OPENAI_API_KEY)."
        )
    embedding_function = OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name=model_name,
    )
    return cast(EmbeddingFunction[Any], embedding_function)


def index_from_config(
    collection: Collection,
    config: Dict[str, ModelConfig],
    batch_size: int,
    *,
    model_registry: Mapping[str, ModelSpec],
    resume: bool = False,
    resume_chunk_size: int = 10000,
    encoder: Any = None,
    token_limit: int = TOKEN_SAFETY_LIMIT,
    completion_state: Optional[Dict[str, Any]] = None,
    completion_state_path: Optional[Path] = None,
    extra_metadata: Optional[Mapping[str, MetadataValue]] = None,
    model_metadata: Optional[Mapping[str, Mapping[str, MetadataValue]]] = None,
) -> Dict[str, int]:
    """Index documents from CSV files into the collection, returning counts per model."""
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if token_limit <= 0 or token_limit > MAX_TOKENS_PER_REQUEST:
        raise ValueError("token_limit must be between 1 and MAX_TOKENS_PER_REQUEST")
    if encoder is None:
        raise ValueError("A token encoder must be supplied for batching logic.")

    completion_state = completion_state or {}
    resume_counts: Counter[str] = Counter()
    resume_missing = 0
    if resume:
        logging.info("Resume mode enabled; preparing existing document counts.")
        missing_models: List[str] = []
        for model_name in config:
            state_entry = completion_state.get(model_name, {})
            count_value = state_entry.get("collection_count")
            if isinstance(count_value, int) and count_value >= 0:
                resume_counts[model_name] = count_value
            elif state_entry.get("started"):
                missing_models.append(model_name)

        if missing_models:
            logging.info(
                "Resume metadata missing counts for %s model(s); "
                "scanning collection to fill gaps.",
                format_int(len(missing_models)),
            )
            total_existing, scanned_counts, resume_missing = summarize_collection(
                collection,
                chunk_size=resume_chunk_size,
                log_progress=True,
            )
            logging.info(
                "Resume scan complete: %s existing document(s) across %d model(s).",
                format_int(total_existing),
                len(scanned_counts),
            )
            if resume_missing:
                logging.warning(
                    "Detected %s document(s) without model metadata; "
                    "they will be ignored for resume calculations.",
                    format_int(resume_missing),
                )
            for model_name, count_value in scanned_counts.items():
                resume_counts[model_name] = count_value
            if completion_state_path:
                try:
                    completion_state_path.parent.mkdir(parents=True, exist_ok=True)
                    for model_name, count_value in scanned_counts.items():
                        entry = completion_state.setdefault(model_name, {})
                        entry.setdefault("started", True)
                        entry.setdefault("collection_count", count_value)
                    completion_state_path.write_text(
                        json.dumps(completion_state, indent=2),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    logging.warning(
                        "Failed to update completion metadata with scanned counts: %s",
                        exc,
                    )
        else:
            total_known = sum(resume_counts.values())
            logging.info(
                "Resume metadata already contains counts for all models; "
                "skipping collection scan (known docs %s).",
                format_int(total_known),
            )

    counts: Dict[str, int] = {}
    for model_name, model_config in config.items():
        csv_path = model_config.path
        if csv_path is None:
            logging.info("Skipping %s: no CSV path provided", model_name)
            continue
        if not csv_path.exists():
            logging.warning(
                "Skipping %s: CSV path %s does not exist", model_name, csv_path
            )
            continue
        current_signature = get_path_signature(csv_path)
        stored_state = completion_state.get(model_name, {})
        if stored_state.get("complete"):
            stored_signature = stored_state.get("source_signature")
            if (
                stored_signature
                and current_signature
                and stored_signature == current_signature
            ):
                logging.info(
                    "Skipping %s: source unchanged since last complete index",
                    model_name,
                )
                counts[model_name] = 0
                continue
            logging.info(
                "Re-indexing %s: source appears to have changed since last run",
                model_name,
            )
        spec = model_registry[model_name]
        existing_count = int(resume_counts.get(model_name, 0)) if resume else 0

        resume_state = ResumeState()
        if resume and isinstance(stored_state, Mapping):
            offset_value = stored_state.get("file_offset")
            if isinstance(offset_value, int) and offset_value >= 0:
                resume_state.offset = offset_value
            row_index_value = stored_state.get("row_index")
            if isinstance(row_index_value, int) and row_index_value >= 0:
                resume_state.row_index = row_index_value
            fieldnames_value = stored_state.get("fieldnames")
            if isinstance(fieldnames_value, list) and all(
                isinstance(item, str) for item in fieldnames_value
            ):
                resume_state.fieldnames = list(fieldnames_value)

        previous_offset = (
            resume_state.offset if resume_state.offset is not None else None
        )
        resume_using_offset = resume and resume_state.offset is not None
        skip_rows = existing_count if resume and not resume_using_offset else 0

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[MetadataDict] = []
        token_counts: List[int] = []
        current_token_total = 0
        added = 0
        batches = 0
        collection_count_so_far = existing_count
        effective_batch_size = min(batch_size, MAX_DOCS_PER_REQUEST)
        if effective_batch_size < batch_size:
            logging.info(
                "Capping batch size for %s to %s documents (API limit; requested %s).",
                model_name,
                format_int(effective_batch_size),
                format_int(batch_size),
            )
        resume_note = ""
        if skip_rows:
            resume_note = (
                f" (skipping {format_int(skip_rows)} previously indexed row(s))"
            )
        elif resume_using_offset and resume_state.offset is not None:
            resume_note = (
                f" (resuming from byte offset {format_int(resume_state.offset)})"
            )
        logging.info("Indexing model %s from %s%s", model_name, csv_path, resume_note)

        current_model_name = model_name

        def persist_state(
            is_complete: bool,
            *,
            documents_indexed: int,
            collection_total: int,
            signature: Optional[Dict[str, float]],
            state: ResumeState,
            model_key: str = current_model_name,
            completion_state_ref: Optional[Dict[str, Any]] = None,
            completion_state_path_ref: Optional[Path] = None,
        ) -> None:
            state_store = (
                completion_state
                if completion_state_ref is None
                else completion_state_ref
            )
            path_ref = (
                completion_state_path
                if completion_state_path_ref is None
                else completion_state_path_ref
            )
            if not path_ref:
                return
            entry = state_store.setdefault(model_key, {})
            entry.update(
                {
                    "complete": bool(is_complete),
                    "indexed_at": datetime.now(timezone.utc)
                    .replace(tzinfo=None)
                    .isoformat(timespec="seconds"),
                    "documents_indexed": documents_indexed,
                    "collection_count": collection_total,
                    "source_signature": signature,
                    "started": True,
                }
            )
            if state.offset is not None:
                entry["file_offset"] = int(state.offset)
            else:
                entry.pop("file_offset", None)
            entry["row_index"] = int(state.row_index)
            if state.fieldnames:
                entry["fieldnames"] = list(state.fieldnames)
            else:
                entry.pop("fieldnames", None)
            try:
                path_ref.parent.mkdir(parents=True, exist_ok=True)
                path_ref.write_text(json.dumps(state_store, indent=2), encoding="utf-8")
            except OSError as exc:
                logging.warning(
                    "Failed to update completion metadata for %s: %s", model_key, exc
                )

        def flush_batch(
            reason: str,
            *,
            ids_ref: List[str],
            documents_ref: List[str],
            metadatas_ref: List[MetadataDict],
            token_counts_ref: List[int],
            model_key: str = current_model_name,
            collection_ref: Collection = collection,
            token_limit_value: int = token_limit,
            signature: Optional[Dict[str, float]] = current_signature,
            state_ref: ResumeState = resume_state,
        ) -> None:
            nonlocal ids, documents, metadatas, token_counts, current_token_total
            nonlocal added, batches, effective_batch_size, collection_count_so_far
            if not ids_ref:
                return

            while ids_ref:
                n = min(len(ids_ref), effective_batch_size)
                emitted_ids = ids_ref[:n]
                emitted_docs = documents_ref[:n]
                emitted_metas: List[MetadataDict] = metadatas_ref[:n]
                emitted_tokens = token_counts_ref[:n]
                emitted_token_total = sum(emitted_tokens)

                try:
                    existing_resp = collection_ref.get(ids=emitted_ids, include=[])
                    existing_list = (
                        existing_resp.get("ids")
                        if isinstance(existing_resp, Mapping)
                        else None
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logging.warning(
                        "Failed to precheck duplicates for %s: %s", model_key, exc
                    )
                    existing_list = None
                if existing_list:
                    existing_set = set(existing_list)
                    removal_indices = [
                        idx
                        for idx, doc_id in enumerate(emitted_ids)
                        if doc_id in existing_set
                    ]
                    if removal_indices:
                        sample = ", ".join(list(existing_set)[:5])
                        if len(existing_set) > 5:
                            sample += ", ..."
                        logging.info(
                            "Preemptively removing %s duplicate id(s) for %s before upsert: %s",
                            format_int(len(removal_indices)),
                            model_key,
                            sample,
                        )
                        for remove_idx in reversed(removal_indices):
                            del ids_ref[remove_idx]
                            del documents_ref[remove_idx]
                            del metadatas_ref[remove_idx]
                            del token_counts_ref[remove_idx]
                        current_token_total = sum(token_counts_ref)
                        if not ids_ref:
                            break
                        continue

                while emitted_token_total > token_limit_value and n > 1:
                    n -= 1
                    emitted_ids = ids_ref[:n]
                    emitted_docs = documents_ref[:n]
                    emitted_metas = metadatas_ref[:n]
                    emitted_tokens = token_counts_ref[:n]
                    emitted_token_total = sum(emitted_tokens)

                if emitted_token_total > token_limit_value:
                    single_tokens = token_counts_ref[0]
                    doc_id = ids_ref[0]
                    if single_tokens > MAX_TOKENS_PER_REQUEST:
                        logging.error(
                            "Skipping document %s in %s: %s tokens exceed hard API limit %s.",
                            doc_id,
                            model_key,
                            format_int(single_tokens),
                            format_int(MAX_TOKENS_PER_REQUEST),
                        )
                        ids_ref.pop(0)
                        documents_ref.pop(0)
                        metadatas_ref.pop(0)
                        token_counts_ref.pop(0)
                        current_token_total = sum(token_counts_ref)
                        continue
                    logging.warning(
                        "Document %s in %s is %s tokens (> %s safety limit); sending alone.",
                        doc_id,
                        model_key,
                        format_int(single_tokens),
                        format_int(token_limit_value),
                    )
                    emitted_ids = ids_ref[:1]
                    emitted_docs = documents_ref[:1]
                    emitted_metas = metadatas_ref[:1]
                    emitted_tokens = token_counts_ref[:1]
                    emitted_token_total = single_tokens
                    n = 1

                if n < effective_batch_size:
                    logging.info(
                        "Adjusting effective batch size for %s from %s to "
                        "%s due to token limits (%s tokens, reason=%s).",
                        model_key,
                        format_int(effective_batch_size),
                        format_int(n),
                        format_int(emitted_token_total),
                        reason,
                    )
                    effective_batch_size = max(1, n)

                retry_after_duplicate = False
                while True:
                    try:
                        collection_ref.upsert(
                            ids=emitted_ids,
                            documents=emitted_docs,
                            metadatas=emitted_metas,  # type: ignore[arg-type]
                        )
                    except chroma_errors.DuplicateIDError as exc:
                        msg = str(exc)
                        dup_set: Optional[set] = getattr(exc, "ids", None)
                        if dup_set is None:
                            dup_matches = re.findall(
                                r"\b[^,\s]+:[0-9a-fA-F]{16,}\b",
                                msg,
                            )
                            dup_set = set(dup_matches)
                        else:
                            dup_set = set(dup_set)
                        if not dup_set:
                            raise
                        before = len(ids_ref)
                        filtered = [
                            (i, d, m, t)
                            for i, d, m, t in zip(
                                ids_ref, documents_ref, metadatas_ref, token_counts_ref
                            )
                            if i not in dup_set
                        ]
                        removed = before - len(filtered)
                        if not removed:
                            raise
                        ids_ref[:] = [i for i, _, _, _ in filtered]
                        documents_ref[:] = [d for _, d, _, _ in filtered]
                        metadatas_ref[:] = [m for _, _, m, _ in filtered]
                        token_counts_ref[:] = [t for _, _, _, t in filtered]
                        current_token_total = sum(token_counts_ref)
                        sample_ids = ", ".join(list(dup_set)[:5])
                        if len(dup_set) > 5:
                            sample_ids += ", ..."
                        logging.warning(
                            "Removed %s duplicate id(s) for %s before retry: %s",
                            format_int(removed),
                            model_key,
                            sample_ids,
                        )
                        retry_after_duplicate = True
                        break
                    else:
                        break

                if retry_after_duplicate:
                    continue

                added += len(emitted_ids)
                batches += 1
                collection_count_so_far += len(emitted_ids)
                logging.info(
                    "Indexed %s batch %d (+%d docs, %s tokens, total %d) [reason=%s]",
                    model_key,
                    batches,
                    len(emitted_ids),
                    format_int(emitted_token_total),
                    added,
                    reason,
                )
                persist_state(
                    False,
                    documents_indexed=added,
                    collection_total=collection_count_so_far,
                    signature=signature,
                    state=state_ref,
                )
                del ids_ref[:n]
                del documents_ref[:n]
                del metadatas_ref[:n]
                del token_counts_ref[:n]
                current_token_total = sum(token_counts_ref)

                if not ids_ref:
                    break

                if (
                    len(ids_ref) < effective_batch_size
                    and current_token_total <= token_limit
                ):
                    break

        skip_state_persisted = False

        def handle_skip_complete(
            callback_state: ResumeState,
            *,
            previous_offset_value: Optional[int] = previous_offset,
            model_key: str = current_model_name,
            signature: Optional[Dict[str, float]] = current_signature,
            added_count: int = added,
            collection_total_value: int = collection_count_so_far,
        ) -> None:
            nonlocal skip_state_persisted
            if skip_state_persisted:
                return
            if (
                previous_offset_value is not None
                and callback_state.offset is not None
                and previous_offset_value > callback_state.offset
            ):
                return
            skip_state_persisted = True
            persist_state(
                False,
                documents_indexed=added_count,
                collection_total=collection_total_value,
                signature=signature,
                state=callback_state,
                model_key=model_key,
            )

        combined_metadata: Optional[Dict[str, MetadataValue]] = None
        if extra_metadata:
            combined_metadata = dict(extra_metadata)
        model_specific = (
            dict(model_metadata.get(model_name, {})) if model_metadata else {}
        )
        schema_version_raw = model_specific.get("schema_version")
        schema_version_int: Optional[int] = None
        if schema_version_raw is not None:
            try:
                schema_version_int = int(schema_version_raw)
            except (TypeError, ValueError):
                schema_version_int = None
            else:
                # type: ignore[assignment]
                model_specific["schema_version"] = schema_version_int
        if model_specific:
            if combined_metadata is None:
                combined_metadata = model_specific
            else:
                combined_metadata.update(model_specific)

        for doc_id, text, metadata in iter_documents(
            model_name,
            csv_path,
            spec,
            model_config.columns,
            skip=skip_rows,
            resume_state=resume_state,
            on_skip_complete=handle_skip_complete if skip_rows else None,
            extra_metadata=combined_metadata,
            schema_version=schema_version_int,
        ):
            token_count = count_tokens(text, encoder)

            if token_count > token_limit:
                if token_count > MAX_TOKENS_PER_REQUEST:
                    logging.error(
                        "Skipping document %s in %s: %s tokens exceed hard API limit %s.",
                        doc_id,
                        model_name,
                        format_int(token_count),
                        format_int(MAX_TOKENS_PER_REQUEST),
                    )
                    continue
                if ids:
                    flush_batch(
                        "pre-token-limit-excess",
                        ids_ref=ids,
                        documents_ref=documents,
                        metadatas_ref=metadatas,
                        token_counts_ref=token_counts,
                    )
                ids.append(doc_id)
                documents.append(text)
                metadatas.append(metadata)
                token_counts.append(token_count)
                current_token_total += token_count
                flush_batch(
                    "single-over-safety",
                    ids_ref=ids,
                    documents_ref=documents,
                    metadatas_ref=metadatas,
                    token_counts_ref=token_counts,
                )
                continue

            if ids and (
                len(ids) >= effective_batch_size
                or current_token_total + token_count > token_limit
            ):
                flush_batch(
                    "threshold-reached",
                    ids_ref=ids,
                    documents_ref=documents,
                    metadatas_ref=metadatas,
                    token_counts_ref=token_counts,
                )

            ids.append(doc_id)
            documents.append(text)
            metadatas.append(metadata)
            token_counts.append(token_count)
            current_token_total += token_count

            if len(ids) >= effective_batch_size:
                flush_batch(
                    "batch-size-limit",
                    ids_ref=ids,
                    documents_ref=documents,
                    metadatas_ref=metadatas,
                    token_counts_ref=token_counts,
                )
            elif current_token_total >= token_limit:
                flush_batch(
                    "token-limit",
                    ids_ref=ids,
                    documents_ref=documents,
                    metadatas_ref=metadatas,
                    token_counts_ref=token_counts,
                )

        flush_batch(
            "final",
            ids_ref=ids,
            documents_ref=documents,
            metadatas_ref=metadatas,
            token_counts_ref=token_counts,
        )

        counts[model_name] = added
        persist_state(
            True,
            documents_indexed=added,
            collection_total=collection_count_so_far,
            signature=current_signature,
            state=resume_state,
        )
        logging.info(
            "Finished indexing %s: %d new document(s) across %d batch(es)%s",
            model_name,
            added,
            batches,
            (
                f" (skipped {format_int(skip_rows)} previously indexed row(s))"
                if skip_rows
                else ""
            ),
        )
    return counts
