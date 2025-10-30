"""Token management utilities for handling oversized documents intelligently."""

from __future__ import annotations

import logging
from typing import Any, List, Sequence, Tuple

from indexer.vectorize_lib.utils import count_tokens


def truncate_text_intelligently(
    text: str,
    max_tokens: int,
    encoder: Any,
    strategy: str = "middle_out",
    preserve_start: int = 500,
    preserve_end: int = 500,
) -> Tuple[str, int, bool]:
    """Intelligently truncate text to fit within token limits while preserving meaning.

    Args:
        text: The text to truncate
        max_tokens: Maximum allowed tokens
        encoder: Token encoder (e.g., tiktoken encoder)
        strategy: Truncation strategy - "middle_out", "end", "start", or "sentences"
        preserve_start: Characters to preserve from start (for middle_out)
        preserve_end: Characters to preserve from end (for middle_out)

    Returns:
        Tuple of (truncated_text, actual_tokens, was_truncated)
    """
    current_tokens = count_tokens(text, encoder)

    if current_tokens <= max_tokens:
        return text, current_tokens, False

    if strategy == "end":
        return _truncate_end(text, max_tokens, encoder)
    elif strategy == "start":
        return _truncate_start(text, max_tokens, encoder)
    elif strategy == "sentences":
        return _truncate_by_sentences(
            text, max_tokens, encoder, preserve_start, preserve_end
        )
    else:  # middle_out (default)
        return _truncate_middle_out(
            text, max_tokens, encoder, preserve_start, preserve_end
        )


def _truncate_end(text: str, max_tokens: int, encoder: Any) -> Tuple[str, int, bool]:
    """Truncate from the end, keeping the beginning intact."""
    # Binary search for the right cutoff point
    suffix = "\n\n[... truncated ...]"
    suffix_tokens = count_tokens(suffix, encoder)

    # Handle very small token limits
    if suffix_tokens >= max_tokens:
        # Even the suffix doesn't fit, just truncate without marker
        left, right = 0, len(text)
        best_text = text
        best_tokens = count_tokens(text, encoder)

        while left <= right:
            mid = (left + right) // 2
            candidate = text[:mid]
            tokens = count_tokens(candidate, encoder)

            if tokens <= max_tokens:
                best_text = candidate
                best_tokens = tokens
                left = mid + 1
            else:
                right = mid - 1

        return best_text, best_tokens, True

    target_tokens = max_tokens - suffix_tokens
    left, right = 0, len(text)
    best_text = ""
    best_tokens = 0

    while left <= right:
        mid = (left + right) // 2
        candidate_content = text[:mid]
        candidate_tokens = count_tokens(candidate_content, encoder)

        if candidate_tokens <= target_tokens:
            # This fits within our target, save it and try for more
            best_text = candidate_content + suffix
            best_tokens = candidate_tokens + suffix_tokens
            left = mid + 1
        else:
            right = mid - 1

    if not best_text:
        # Emergency fallback - just use suffix alone
        best_text = suffix
        best_tokens = suffix_tokens

    return best_text, best_tokens, True


def _truncate_start(text: str, max_tokens: int, encoder: Any) -> Tuple[str, int, bool]:
    """Truncate from the start, keeping the end intact."""
    # Binary search from the end
    prefix = "[... truncated ...]\n\n"
    prefix_tokens = count_tokens(prefix, encoder)

    # Handle very small token limits
    if prefix_tokens >= max_tokens:
        # Even the prefix doesn't fit, just truncate without marker
        left, right = 0, len(text)
        best_text = text
        best_tokens = count_tokens(text, encoder)

        while left <= right:
            mid = (left + right) // 2
            candidate = text[mid:]
            tokens = count_tokens(candidate, encoder)

            if tokens <= max_tokens:
                best_text = candidate
                best_tokens = tokens
                right = mid - 1
            else:
                left = mid + 1

        return best_text, best_tokens, True

    target_tokens = max_tokens - prefix_tokens
    left, right = 0, len(text)
    best_text = ""
    best_tokens = 0

    while left <= right:
        mid = (left + right) // 2
        candidate_content = text[mid:]
        candidate_tokens = count_tokens(candidate_content, encoder)

        if candidate_tokens <= target_tokens:
            # This fits within our target, save it and try to include more from start
            best_text = prefix + candidate_content
            best_tokens = prefix_tokens + candidate_tokens
            right = mid - 1
        else:
            left = mid + 1

    if not best_text:
        # Emergency fallback - just use prefix alone
        best_text = prefix
        best_tokens = prefix_tokens

    return best_text, best_tokens, True


def _truncate_middle_out(
    text: str,
    max_tokens: int,
    encoder: Any,
    preserve_start: int,
    preserve_end: int,
) -> Tuple[str, int, bool]:
    """Truncate from the middle, preserving start and end.

    This is ideal for documents where both the beginning (e.g., title, summary)
    and end (e.g., conclusions, recent updates) are important.
    """
    middle_marker = "\n\n[... truncated ...]\n\n"
    marker_tokens = count_tokens(middle_marker, encoder)

    # Handle very small token limits
    if marker_tokens >= max_tokens:
        # Fall back to simple truncation from end
        return _truncate_end(text, max_tokens, encoder)

    # Binary search on the amount to preserve from each end
    target_tokens = max_tokens - marker_tokens
    left, right = 0, len(text) // 2

    best_text = ""
    best_tokens = marker_tokens

    while left <= right:
        mid = (left + right) // 2

        # Try preserving 'mid' characters from each end
        start_part = text[:mid]
        end_part = text[-mid:] if mid > 0 else ""

        # Calculate tokens for the parts only (not including marker yet)
        start_tokens = count_tokens(start_part, encoder)
        end_tokens = count_tokens(end_part, encoder) if end_part else 0
        total_content_tokens = start_tokens + end_tokens

        if total_content_tokens <= target_tokens:
            # This fits! Save it and try for more
            best_text = start_part + middle_marker + end_part
            best_tokens = total_content_tokens + marker_tokens
            left = mid + 1
        else:
            right = mid - 1

    if not best_text:
        # Emergency fallback - just use the marker
        best_text = middle_marker
        best_tokens = marker_tokens

    return best_text, best_tokens, True


def _truncate_by_sentences(
    text: str,
    max_tokens: int,
    encoder: Any,
    preserve_start: int,
    preserve_end: int,
) -> Tuple[str, int, bool]:
    """Truncate by complete sentences to maintain readability.

    Preserves sentences from start and end, removes middle sentences.
    """
    middle_marker = "\n\n[... truncated ...]\n\n"
    marker_tokens = count_tokens(middle_marker, encoder)

    # Handle very small token limits
    if marker_tokens >= max_tokens or max_tokens < 20:
        # Fall back to middle_out for very small limits
        return _truncate_middle_out(
            text, max_tokens, encoder, preserve_start, preserve_end
        )

    # Simple sentence splitting (can be enhanced with nltk if needed)
    sentences = _split_sentences(text)

    if len(sentences) <= 2:
        # Too few sentences, fall back to character truncation
        return _truncate_middle_out(
            text, max_tokens, encoder, preserve_start, preserve_end
        )

    # Try to keep as many sentences from start and end as possible
    start_sentences: List[str] = []
    end_sentences: List[str] = []

    # Reserve space for the marker
    available_tokens = max_tokens - marker_tokens

    # Greedily add sentences from start (up to half the available space)
    current_text = ""
    for sentence in sentences:
        candidate = current_text + sentence + " "
        if count_tokens(candidate, encoder) <= available_tokens // 2:
            start_sentences.append(sentence)
            current_text = candidate
        else:
            break

    # Calculate remaining tokens
    start_text = " ".join(start_sentences)
    start_tokens = count_tokens(start_text, encoder)
    remaining_tokens = available_tokens - start_tokens

    # Greedily add sentences from end with remaining space
    current_text = ""
    for sentence in reversed(sentences):
        candidate = sentence + " " + current_text
        if count_tokens(candidate, encoder) <= remaining_tokens:
            end_sentences.insert(0, sentence)
            current_text = candidate
        else:
            break

    # Remove duplicates (sentences that appear in both start and end)
    start_set = set(start_sentences)
    end_sentences = [s for s in end_sentences if s not in start_set]

    if start_sentences or end_sentences:
        result = start_text + middle_marker + " ".join(end_sentences)
        tokens = count_tokens(result, encoder)
        # Verify we didn't exceed the limit
        if tokens <= max_tokens:
            return result, tokens, True

    # Fallback if sentence approach didn't work or exceeded limit
    return _truncate_middle_out(text, max_tokens, encoder, preserve_start, preserve_end)


def _split_sentences(text: str) -> List[str]:
    """Simple sentence splitter. Can be enhanced with NLTK or spaCy if needed."""
    import re

    # Split on common sentence endings
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def suggest_truncation_strategy(
    text: str,
    model_name: str,
    semantic_fields: Sequence[str],
) -> str:
    """Suggest the best truncation strategy based on document characteristics.

    Args:
        text: The document text
        model_name: Name of the model (e.g., "Table", "Field")
        semantic_fields: Sequence of semantic field names

    Returns:
        Strategy name: "middle_out", "end", "start", or "sentences"
    """
    text_lower = text.lower()
    line_count = text.count("\n")

    # Tables often have descriptions at the top
    if model_name == "Table" or "table" in text_lower[:200]:
        return "end"  # Keep the beginning (table name, description)

    # Documentation or help text - keep start and end
    if any(
        field in ("documentation", "help_text", "description")
        for field in semantic_fields
    ):
        return "sentences"  # Maintain readability

    # Configuration or technical specs - keep everything structured
    if line_count > 50 and ("field" in text_lower or "parameter" in text_lower):
        return "middle_out"  # Preserve structure from both ends

    # Default: preserve start and end
    return "middle_out"


def log_truncation_stats(
    doc_id: str,
    model_name: str,
    original_tokens: int,
    final_tokens: int,
    strategy: str,
) -> None:
    """Log truncation statistics for monitoring and debugging."""
    reduction_pct = ((original_tokens - final_tokens) / original_tokens) * 100
    logging.warning(
        "Document %s (%s) truncated: %d → %d tokens (%.1f%% reduction) using strategy '%s'",
        doc_id,
        model_name,
        original_tokens,
        final_tokens,
        reduction_pct,
        strategy,
    )
