"""Collection naming strategies for vectorize CLI."""

from dataclasses import dataclass
from typing import Optional, Protocol


class CollectionStrategy(Protocol):
    """Protocol for resolving Chroma collection names."""

    def collection_name(self, partition_name: Optional[str]) -> str:
        """Return the target collection name for the given partition."""
        ...


@dataclass(frozen=True)
class FixedCollectionStrategy:
    """Always return the same collection name."""

    name: str

    def collection_name(self, partition_name: Optional[str]) -> str:
        return self.name


@dataclass(frozen=True)
class PartitionCollectionStrategy:
    """Derive collection names from partition identifiers."""

    prefix: Optional[str] = None

    def collection_name(self, partition_name: Optional[str]) -> str:
        if partition_name is None:
            if self.prefix is not None:
                return self.prefix
            raise ValueError(
                "Partition-scoped collection strategy requires a partition name."
            )
        if self.prefix:
            return f"{self.prefix}_{partition_name}"
        return partition_name
