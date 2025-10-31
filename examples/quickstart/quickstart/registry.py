"""Pydantic model registry used by the quickstart example."""

from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel

from indexer.models import ModelSpec


class Contract(BaseModel):
    """Minimal contract card used in the quickstart demo."""

    id: str
    title: str
    summary: str


MODEL_REGISTRY: Mapping[str, ModelSpec] = {
    "Contract": ModelSpec(
        model=Contract,
        semantic_fields=("summary", "title"),
        keyword_fields=("id", "title"),
    )
}
