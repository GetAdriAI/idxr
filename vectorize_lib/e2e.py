"""Helpers for vectorize end-to-end sampling runs."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List
from .documents import MetadataDict


@dataclass
class SampledDocument:
    """Container for a sampled document during an E2E test run."""

    row_index: int
    doc_id: str
    text: str
    metadata: MetadataDict


class ReservoirSampler:
    """Reservoir sampler that retains a fixed number of random items."""

    def __init__(self, capacity: int, rng: random.Random) -> None:
        self.capacity = max(0, int(capacity))
        self._rng = rng
        self._items: List[SampledDocument] = []
        self._seen = 0

    def offer(self, item: SampledDocument) -> None:
        if self.capacity <= 0:
            return
        self._seen += 1
        if len(self._items) < self.capacity:
            self._items.append(item)
            return
        j = self._rng.randint(1, self._seen)
        if j <= self.capacity:
            self._items[j - 1] = item

    def results(self) -> List[SampledDocument]:
        return list(self._items)


@dataclass
class E2ETestRecorder:
    """Collect and persist sampled document metadata for auditing."""

    output_path: Path
    entries: List[dict] = field(default_factory=list)

    def record(
        self,
        *,
        model_name: str,
        csv_path: Path,
        sample: SampledDocument,
    ) -> None:
        text_preview = sample.text[:200]
        entry = {
            "model": model_name,
            "csv_path": str(csv_path),
            "row_index": sample.row_index,
            "doc_id": sample.doc_id,
            "metadata": sample.metadata,
            "text_preview": text_preview,
            "partition": sample.metadata.get("partition_name"),
        }
        self.entries.append(entry)

    def write(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as handle:
            json.dump(self.entries, handle, indent=2)


@dataclass
class E2ETestConfig:
    """Configuration describing how to execute an E2E sampling run."""

    sample_size: int
    recorder: E2ETestRecorder
    rng: random.Random

    def sample_documents(
        self,
        *,
        model_name: str,
        csv_path: Path,
        documents: Iterable[tuple[int, str, str, MetadataDict]],
    ) -> List[SampledDocument]:
        sampler = ReservoirSampler(self.sample_size, self.rng)
        for row_index, doc_id, text, metadata in documents:
            sampler.offer(
                SampledDocument(
                    row_index=row_index,
                    doc_id=doc_id,
                    text=text,
                    metadata=metadata,
                )
            )
        samples = sampler.results()
        for sample in samples:
            self.recorder.record(
                model_name=model_name,
                csv_path=csv_path,
                sample=sample,
            )
        return samples
