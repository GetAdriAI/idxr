"""Indexing pipeline that streams CSV rows into ChromaDB."""

from __future__ import annotations

import json
import logging
import os
import re
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, cast

from chromadb import errors as chroma_errors
from chromadb.api import Collection
from chromadb.utils.embedding_functions import (
    EmbeddingFunction,
    OpenAIEmbeddingFunction,
)

from .compact import (
    CHROMA_DOCUMENT_SIZE_LIMIT,
    DocumentCompactor,
)
from .configuration import ModelConfig
from .documents import (
    MetadataDict,
    MetadataValue,
    ResumeState,
    iter_documents,
)
from .e2e import E2ETestConfig
from .token_management import (
    truncate_text_intelligently,
    suggest_truncation_strategy,
    log_truncation_stats,
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


def _write_error_report(
    *,
    error_dir: Optional[Path],
    model_name: str,
    collection_name: Optional[str],
    reason: str,
    source_csv: Path,
    emitted_ids: Sequence[str],
    emitted_docs: Sequence[str],
    emitted_metas: Sequence[MetadataDict],
    emitted_rows: Sequence[int],
    token_counts: Sequence[int],
    token_total: int,
    resume_state: ResumeState,
    exception: BaseException,
    traceback_text: str,
) -> Optional[Path]:
    """Persist error context for failed batches to a YAML-compatible file."""

    if error_dir is None:
        return None

    try:
        target_root = (error_dir / "errors").resolve()
        target_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logging.warning(
            "Unable to prepare error directory %s for %s: %s",
            error_dir,
            model_name,
            exc,
        )
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    timestamp = now.isoformat(timespec="seconds")
    sortable_stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
    safe_model = re.sub(r"[^0-9A-Za-z_.-]", "_", model_name) or "model"
    filename = f"{sortable_stamp}_{safe_model}.yaml"
    candidate = target_root / filename
    counter = 1
    while candidate.exists():
        candidate = target_root / f"{sortable_stamp}_{safe_model}_{counter}.yaml"
        counter += 1

    partition_names = {
        meta.get("partition_name")
        for meta in emitted_metas
        if isinstance(meta, Mapping) and meta.get("partition_name")
    }
    partition_name = None
    if partition_names:
        partition_name = next(iter(partition_names))

    rows_payload: List[Dict[str, Any]] = []
    for row_idx, doc_id, document, metadata, token_count in zip(
        emitted_rows,
        emitted_ids,
        emitted_docs,
        emitted_metas,
        token_counts,
    ):
        rows_payload.append(
            {
                "row_index": int(row_idx),
                "id": doc_id,
                "document": document,
                "metadata": metadata,
                "token_count": int(token_count),
            }
        )

    resume_payload: Dict[str, Any] = {
        "row_index": int(getattr(resume_state, "row_index", 0)),
    }
    if getattr(resume_state, "offset", None) is not None:
        resume_payload["offset"] = int(cast(int, resume_state.offset))
    if getattr(resume_state, "fieldnames", None):
        resume_payload["fieldnames"] = list(cast(List[str], resume_state.fieldnames))

    payload: Dict[str, Any] = {
        "timestamp": timestamp,
        "model": model_name,
        "collection": collection_name,
        "partition_name": partition_name,
        "source_csv": str(source_csv),
        "reason": reason,
        "batch": {
            "size": len(emitted_ids),
            "token_total": int(token_total),
        },
        "resume_state": resume_payload,
        "rows": rows_payload,
        "exception": {
            "type": exception.__class__.__name__,
            "message": str(exception),
            "traceback": traceback_text,
        },
    }

    try:
        try:
            import yaml  # type: ignore
        except ImportError:  # pragma: no cover - optional dependency
            yaml = None  # type: ignore

        if yaml is not None:  # type: ignore
            serialized = yaml.safe_dump(payload, sort_keys=False)  # type: ignore
        else:
            serialized = json.dumps(payload, indent=2)

        candidate.write_text(serialized, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - defensive
        logging.warning("Failed to write error report %s: %s", candidate, exc)
        return None

    return candidate


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
    compactor: Optional[DocumentCompactor] = None,
    token_limit: int = TOKEN_SAFETY_LIMIT,
    embedding_token_limit: int = 8191,
    completion_state: Optional[Dict[str, Any]] = None,
    completion_state_path: Optional[Path] = None,
    extra_metadata: Optional[Mapping[str, MetadataValue]] = None,
    model_metadata: Optional[Mapping[str, Mapping[str, MetadataValue]]] = None,
    e2e_config: Optional[E2ETestConfig] = None,
    error_report_dir: Optional[Path] = None,
    collection_name: Optional[str] = None,
    default_truncation_strategy: str = "auto",
) -> Dict[str, int]:
    """Index documents from CSV files into the collection, returning counts per model."""
    if batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if token_limit <= 0 or token_limit > MAX_TOKENS_PER_REQUEST:
        raise ValueError("token_limit must be between 1 and MAX_TOKENS_PER_REQUEST")
    if encoder is None:
        raise ValueError("A token encoder must be supplied for batching logic.")
    if e2e_config and resume:
        raise ValueError("E2E test runs do not support resume mode.")

    completion_state = completion_state or {}
    if error_report_dir is None and completion_state_path is not None:
        error_report_dir = completion_state_path.parent
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

        if e2e_config is not None:
            resume_state = ResumeState()
            skip_rows = 0
            previous_offset = None
            resume_using_offset = False

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[MetadataDict] = []
        token_counts: List[int] = []
        row_numbers: List[int] = []
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
            row_numbers_ref: List[int],
            model_key: str = current_model_name,
            collection_ref: Collection = collection,
            token_limit_value: int = token_limit,
            signature: Optional[Dict[str, float]] = current_signature,
            state_ref: ResumeState = resume_state,
            source_csv: Path,
            batch_limit: int,
            error_dir: Optional[Path] = error_report_dir,
            collection_value: Optional[str] = collection_name,
        ) -> int:
            nonlocal ids, documents, metadatas, token_counts, row_numbers
            nonlocal current_token_total, added, batches, effective_batch_size
            nonlocal collection_count_so_far

            local_batch_size = batch_limit

            if not ids_ref:
                return batch_limit

            while ids_ref:
                n = min(len(ids_ref), local_batch_size)
                emitted_ids = ids_ref[:n]
                emitted_docs = documents_ref[:n]
                emitted_metas: List[MetadataDict] = metadatas_ref[:n]
                emitted_tokens = token_counts_ref[:n]
                emitted_rows = row_numbers_ref[:n]
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
                            del row_numbers_ref[remove_idx]
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
                    emitted_rows = row_numbers_ref[:n]
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
                    emitted_rows = row_numbers_ref[:1]
                    emitted_token_total = single_tokens
                    n = 1

                if n < local_batch_size:
                    logging.info(
                        "Adjusting effective batch size for %s from %s to "
                        "%s due to token limits (%s tokens, reason=%s).",
                        model_key,
                        format_int(effective_batch_size),
                        format_int(n),
                        format_int(emitted_token_total),
                        reason,
                    )
                    batch_limit = max(1, n)
                    effective_batch_size = batch_limit
                    local_batch_size = batch_limit

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
                            (i, d, m, t, r)
                            for i, d, m, t, r in zip(
                                ids_ref,
                                documents_ref,
                                metadatas_ref,
                                token_counts_ref,
                                row_numbers_ref,
                            )
                            if i not in dup_set
                        ]
                        removed = before - len(filtered)
                        if not removed:
                            raise
                        ids_ref[:] = [i for i, _, _, _, _ in filtered]
                        documents_ref[:] = [d for _, d, _, _, _ in filtered]
                        metadatas_ref[:] = [m for _, _, m, _, _ in filtered]
                        token_counts_ref[:] = [t for _, _, _, t, _ in filtered]
                        row_numbers_ref[:] = [r for _, _, _, _, r in filtered]
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
                    except Exception as exc:  # pragma: no cover - defensive
                        traceback_text = traceback.format_exc()
                        error_path = _write_error_report(
                            error_dir=error_dir,
                            model_name=model_key,
                            collection_name=collection_value,
                            reason=reason,
                            source_csv=source_csv,
                            emitted_ids=emitted_ids,
                            emitted_docs=emitted_docs,
                            emitted_metas=emitted_metas,
                            emitted_rows=emitted_rows,
                            token_counts=emitted_tokens,
                            token_total=emitted_token_total,
                            resume_state=state_ref,
                            exception=exc,
                            traceback_text=traceback_text,
                        )
                        try:
                            context_chunks = []
                            for doc_id, row_num, meta in zip(
                                emitted_ids, emitted_rows, emitted_metas
                            ):
                                try:
                                    metadata_bytes = len(json.dumps(meta, default=str))
                                except (TypeError, ValueError):
                                    metadata_bytes = -1
                                context_chunks.append(
                                    f"id={doc_id} row={row_num} metadata_bytes={metadata_bytes}"
                                )
                            context_summary = (
                                "; ".join(context_chunks)
                                if context_chunks
                                else "no rows"
                            )
                        except Exception:  # pragma: no cover - defensive
                            context_summary = "unable to summarise batch"
                        logging.exception(
                            "Chroma upsert failed for model %s (csv=%s, reason=%s). Rows: %s",
                            model_key,
                            source_csv,
                            reason,
                            context_summary,
                        )
                        if error_path is not None:
                            logging.error(
                                "Error report for model %s persisted to %s",
                                model_key,
                                error_path,
                            )
                        raise
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
                del row_numbers_ref[:n]
                current_token_total = sum(token_counts_ref)

                if not ids_ref:
                    break

                if (
                    len(ids_ref) < local_batch_size
                    and current_token_total <= token_limit
                ):
                    break

            return batch_limit

        compactor_ref: Optional[DocumentCompactor] = compactor
        compactor_init_failed = False

        def get_document_compactor() -> Optional[DocumentCompactor]:
            nonlocal compactor_ref, compactor_init_failed
            if compactor_ref is not None:
                return compactor_ref
            if compactor_init_failed:
                return None
            try:
                compactor_ref = DocumentCompactor()
            except Exception as exc:
                logging.error("Unable to initialize document compactor: %s", exc)
                compactor_init_failed = True
                return None
            return compactor_ref

        def hard_trim_to_byte_limit(
            value: str, limit: int = CHROMA_DOCUMENT_SIZE_LIMIT
        ) -> str:
            encoded = value.encode("utf-8")
            if len(encoded) <= limit:
                return value
            return encoded[:limit].decode("utf-8", errors="ignore").rstrip()

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

        def process_document(
            _row_number: int,
            doc_id: str,
            text: str,
            metadata: MetadataDict,
            source_csv: Path,
            ids_list: List[str] = ids,
            documents_list: List[str] = documents,
            metadatas_list: List[MetadataDict] = metadatas,
            token_counts_list: List[int] = token_counts,
            row_numbers_list: List[int] = row_numbers,
            model_key: str = current_model_name,
            model_config_ref: ModelConfig = model_config,
            spec_ref: ModelSpec = spec,
        ) -> None:
            nonlocal current_token_total, effective_batch_size

            current_batch_size = effective_batch_size

            original_bytes = len(text.encode("utf-8"))
            if original_bytes > CHROMA_DOCUMENT_SIZE_LIMIT:
                metadata["original_bytes"] = int(original_bytes)
                compactor_instance = get_document_compactor()
                if compactor_instance is not None:
                    result = compactor_instance.compact(
                        doc_id=doc_id,
                        text=text,
                        model_name=model_key,
                        target_bytes=CHROMA_DOCUMENT_SIZE_LIMIT,
                    )
                    text = result.text
                    if result.was_compacted:
                        metadata["compacted"] = True
                adjusted_bytes = len(text.encode("utf-8"))
                if adjusted_bytes > CHROMA_DOCUMENT_SIZE_LIMIT:
                    logging.warning(
                        (
                            "Document %s in %s still exceeds %s bytes after "
                            "compaction attempt; applying hard trim."
                        ),
                        doc_id,
                        model_key,
                        format_int(CHROMA_DOCUMENT_SIZE_LIMIT),
                    )
                    text = hard_trim_to_byte_limit(text, CHROMA_DOCUMENT_SIZE_LIMIT)
                    adjusted_bytes = len(text.encode("utf-8"))
                    metadata["compaction_fallback"] = "hard_trim"
                    metadata["compacted"] = True
                if adjusted_bytes != original_bytes:
                    metadata["compacted_bytes"] = int(adjusted_bytes)
            token_count = count_tokens(text, encoder)
            current_batch_size = effective_batch_size

            # Handle oversized documents with intelligent truncation
            # embedding_token_limit is the per-document token limit (e.g., 8191 for OpenAI)
            # This is different from token_limit which is for batch-level limits
            if token_count > embedding_token_limit:
                logging.warning(
                    "Document %s in %s has %s tokens (exceeds limit %s). "
                    "Applying intelligent truncation.",
                    doc_id,
                    model_key,
                    format_int(token_count),
                    format_int(embedding_token_limit),
                )

                # Determine truncation strategy with precedence:
                # 1. Per-model config (most specific)
                # 2. CLI argument (global default)
                # 3. Auto-detection (fallback)
                strategy = model_config_ref.truncation_strategy
                if strategy is None or strategy == "auto":
                    strategy = default_truncation_strategy
                if strategy == "auto":
                    strategy = suggest_truncation_strategy(
                        text,
                        model_key,
                        spec_ref.semantic_fields,
                    )

                # Truncate intelligently, leaving some headroom for safety
                target_tokens = int(embedding_token_limit * 0.95)  # 5% safety margin
                truncated_text, final_tokens, was_truncated = (
                    truncate_text_intelligently(
                        text,
                        max_tokens=target_tokens,
                        encoder=encoder,
                        strategy=strategy,
                    )
                )

                if was_truncated:
                    # Log truncation statistics
                    log_truncation_stats(
                        doc_id,
                        model_key,
                        token_count,
                        final_tokens,
                        strategy,
                    )

                    # Use truncated version
                    text = truncated_text
                    token_count = final_tokens

                    # Add metadata flag to indicate truncation
                    metadata["truncated"] = True
                    metadata["original_tokens"] = int(token_count)
                else:
                    # Should not happen, but fallback to skip
                    logging.error(
                        "Failed to truncate document %s in %s. Skipping.",
                        doc_id,
                        model_key,
                    )
                    return

            if token_count > token_limit:
                if ids_list:
                    effective_batch_size = flush_batch(
                        "pre-token-limit-excess",
                        ids_ref=ids_list,
                        documents_ref=documents_list,
                        metadatas_ref=metadatas_list,
                        token_counts_ref=token_counts_list,
                        row_numbers_ref=row_numbers_list,
                        source_csv=source_csv,
                        batch_limit=effective_batch_size,
                    )
                    current_batch_size = effective_batch_size
                ids_list.append(doc_id)
                documents_list.append(text)
                metadatas_list.append(metadata)
                token_counts_list.append(token_count)
                row_numbers_list.append(_row_number)
                current_token_total += token_count
                effective_batch_size = flush_batch(
                    "single-over-safety",
                    ids_ref=ids_list,
                    documents_ref=documents_list,
                    metadatas_ref=metadatas_list,
                    token_counts_ref=token_counts_list,
                    row_numbers_ref=row_numbers_list,
                    source_csv=source_csv,
                    batch_limit=effective_batch_size,
                )
                current_batch_size = effective_batch_size
                return

            if ids_list and (
                len(ids_list) >= current_batch_size
                or current_token_total + token_count > token_limit
            ):
                effective_batch_size = flush_batch(
                    "threshold-reached",
                    ids_ref=ids_list,
                    documents_ref=documents_list,
                    metadatas_ref=metadatas_list,
                    token_counts_ref=token_counts_list,
                    row_numbers_ref=row_numbers_list,
                    source_csv=source_csv,
                    batch_limit=current_batch_size,
                )
                current_batch_size = effective_batch_size

            ids_list.append(doc_id)
            documents_list.append(text)
            metadatas_list.append(metadata)
            token_counts_list.append(token_count)
            row_numbers_list.append(_row_number)
            current_token_total += token_count

            current_batch_size = effective_batch_size

            if len(ids_list) >= current_batch_size:
                effective_batch_size = flush_batch(
                    "batch-size-limit",
                    ids_ref=ids_list,
                    documents_ref=documents_list,
                    metadatas_ref=metadatas_list,
                    token_counts_ref=token_counts_list,
                    row_numbers_ref=row_numbers_list,
                    source_csv=source_csv,
                    batch_limit=current_batch_size,
                )
                current_batch_size = effective_batch_size
            elif current_token_total >= token_limit:
                effective_batch_size = flush_batch(
                    "token-limit",
                    ids_ref=ids_list,
                    documents_ref=documents_list,
                    metadatas_ref=metadatas_list,
                    token_counts_ref=token_counts_list,
                    row_numbers_ref=row_numbers_list,
                    source_csv=source_csv,
                    batch_limit=current_batch_size,
                )
                current_batch_size = effective_batch_size
            return

        document_iterable = iter_documents(
            model_name,
            csv_path,
            spec,
            model_config.columns,
            skip=skip_rows,
            resume_state=resume_state,
            on_skip_complete=handle_skip_complete if skip_rows else None,
            extra_metadata=combined_metadata,
            schema_version=schema_version_int,
        )

        if e2e_config is not None:
            sampled_documents = e2e_config.sample_documents(
                model_name=model_name,
                csv_path=csv_path,
                documents=document_iterable,
            )
            for sample in sampled_documents:
                process_document(
                    sample.row_index,
                    sample.doc_id,
                    sample.text,
                    sample.metadata,
                    source_csv=csv_path,
                )
        else:
            for row_index, doc_id, text, metadata in document_iterable:
                process_document(
                    row_index,
                    doc_id,
                    text,
                    metadata,
                    source_csv=csv_path,
                )

        effective_batch_size = flush_batch(
            "final",
            ids_ref=ids,
            documents_ref=documents,
            metadatas_ref=metadatas,
            token_counts_ref=token_counts,
            row_numbers_ref=row_numbers,
            source_csv=csv_path,
            batch_limit=effective_batch_size,
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
