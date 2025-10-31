"""LLM-powered agent that compacts oversized documents before indexing."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Sequence, cast

from openai import APIError, OpenAI, OpenAIError

CHROMA_DOCUMENT_SIZE_LIMIT = 16_384


class _ResponsesClient(Protocol):
    """Protocol covering the subset of the OpenAI client we rely on."""

    def create(self, **kwargs: object) -> "_ResponseProtocol": ...


class _ResponseProtocol(Protocol):
    """Protocol for the response object returned by the OpenAI SDK."""

    @property
    def output_text(self) -> str: ...


class _OpenAIClient(Protocol):
    """Protocol abstraction to simplify testing."""

    @property
    def responses(self) -> _ResponsesClient: ...


@dataclass
class CompactionResult:
    """Container for the outcome of an LLM compaction attempt."""

    text: str
    was_compacted: bool


class DocumentCompactor:
    """LLM-backed document compactor that honors ChromaDB's 16 KB limit."""

    def __init__(
        self,
        *,
        client: Optional[_OpenAIClient] = None,
        prompt_path: Optional[Path] = None,
        model: Optional[str] = None,
        target_bytes: int = CHROMA_DOCUMENT_SIZE_LIMIT,
    ) -> None:
        self._target_bytes = max(1, target_bytes)
        system_prompt_path = prompt_path or Path(__file__).with_name(
            "compact-prompt.md"
        )
        self._system_prompt = system_prompt_path.read_text(encoding="utf-8").strip()

        api_key = os.getenv("OPENAI_API_KEY")
        if client is None:
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY environment variable is required for document compaction."
                )
            client = cast(_OpenAIClient, OpenAI(api_key=api_key))
        self._client: _OpenAIClient = client

        resolved_model = model or os.getenv("OPENAI_MODEL")
        if not resolved_model:
            raise RuntimeError(
                "OPENAI_MODEL environment variable is required for document compaction."
            )
        self._model = resolved_model

    @property
    def target_bytes(self) -> int:
        """Expose the enforced byte budget for documents."""
        return self._target_bytes

    def compact(
        self,
        *,
        doc_id: str,
        text: str,
        model_name: Optional[str] = None,
        target_bytes: Optional[int] = None,
        extra_context: Optional[Sequence[str]] = None,
    ) -> CompactionResult:
        """Compact a document so it fits within ChromaDB's byte budget.

        Returns the compacted text and whether the document was modified.
        If the LLM call fails, falls back to deterministic trimming.
        """
        budget = max(1, target_bytes or self._target_bytes)
        original_bytes = len(text.encode("utf-8"))
        if original_bytes <= budget:
            return CompactionResult(text=text, was_compacted=False)

        payload_sections = [
            f"target_characters={budget}",
            f"document_id={doc_id}",
        ]
        if model_name:
            payload_sections.append(f"model_name={model_name}")
        if extra_context:
            payload_sections.extend(extra_context)

        payload_sections.append("----- BEGIN SOURCE DOCUMENT -----")
        payload_sections.append(text)
        payload_sections.append("----- END SOURCE DOCUMENT -----")

        user_content = "\n".join(payload_sections)

        compacted_text: Optional[str] = None
        try:
            response = self._client.responses.create(
                model=self._model,
                input=[
                    {
                        "role": "system",
                        "content": [
                            {"type": "input_text", "text": self._system_prompt}
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_content}],
                    },
                ],
                tools=[
                    {
                        "type": "code_interpreter",
                        "container": {"type": "auto"},
                    }
                ],
            )
            compacted_text = response.output_text.strip()
        except (APIError, OpenAIError, OSError) as exc:
            logging.error(
                "Failed to compact document %s with OpenAI model %s: %s",
                doc_id,
                self._model,
                exc,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logging.exception(
                "Unexpected error while compacting document %s: %s", doc_id, exc
            )

        if not compacted_text:
            compacted_text = text

        normalized = self._enforce_budget(compacted_text, budget)
        was_compacted = normalized != text

        if was_compacted:
            logging.info(
                "Compacted document %s from %d bytes to %d bytes.",
                doc_id,
                original_bytes,
                len(normalized.encode("utf-8")),
            )

        return CompactionResult(text=normalized, was_compacted=was_compacted)

    def _enforce_budget(self, text: str, budget: int) -> str:
        """Ensure text does not exceed the byte budget with a hard trim fallback."""
        encoded = text.encode("utf-8")
        if len(encoded) <= budget:
            return text
        trimmed = encoded[:budget].decode("utf-8", errors="ignore")
        return trimmed.rstrip()


__all__ = ["CHROMA_DOCUMENT_SIZE_LIMIT", "CompactionResult", "DocumentCompactor"]
