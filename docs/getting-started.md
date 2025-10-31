# Getting Started

This guide walks you from a clean environment to a working idxr pipeline in minutes.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install idxr
```

### Optional helpers

Install `mkdocs` if you plan to build the documentation locally:

```bash
pip install mkdocs
```

## Quickstart Example

The public idxr repository ships a miniature dataset that exercises the full lifecycle—manifest generation, partitioning, and vectorization into an in-memory Chroma collection.

```bash
# Clone the repository (or download the tarball) and jump into the example
git clone https://github.com/GetAdriAI/idxr.git
cd idxr/examples/quickstart

# Create an isolated environment for the demo
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Provide credentials for embeddings (required by default strategies)
export OPENAI_API_KEY="sk-your-key"

# 1. Prepare dataset partitions
idxr prepare_datasets \
  --model quickstart.registry:MODEL_REGISTRY \
  --config config/prepare_datasets_config.json \
  --output-root workdir/partitions

# 2. Index the generated partitions into a local Chroma store
idxr vectorize index \
  --model quickstart.registry:MODEL_REGISTRY \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --collection quickstart \
  --batch-size 50 \
  --resume

# 3. Inspect indexing status
idxr vectorize status \
  --model quickstart.registry:MODEL_REGISTRY \
  --partition-dir workdir/partitions \
  --partition-out-dir workdir/chroma_partitions
```

Each command is self-contained—configs live under `examples/quickstart/config`, the demo registry is in `quickstart/registry.py`, and the sample CSV resides in `data/contracts.csv`. Change file paths or models to plug in your own domain once you are comfortable with the workflow.

## Next Steps

* Read the [Prepare Datasets overview](prepare-datasets/overview.md) to understand how manifests are stitched together.
* Explore the [Vectorize overview](vectorize/overview.md) to learn how idxr batches and truncates content.
* Consult the argument reference pages whenever you introduce new flags into your automation.
