from dataclasses import dataclass
from typing import Sequence, Type

from pydantic import BaseModel


@dataclass(frozen=True)
class ModelSpec:
    """Describes how a Pydantic model should be indexed."""

    model: Type[BaseModel]
    semantic_fields: Sequence[str]
    keyword_fields: Sequence[str]
