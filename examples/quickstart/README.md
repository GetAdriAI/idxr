# Quickstart Scenario

This directory bundles a self-contained dataset, config, and registry so you can exercise the idxr lifecycle locally.

## Layout

- `config/prepare_datasets_config.json` – mapping between the `Contract` model and the demo CSV.
- `config/vectorize_config.json` – optional direct-index config.
- `data/contracts.csv` – three toy rows describing ECC knowledge base assets.
- `quickstart/registry.py` – Pydantic model and `MODEL_REGISTRY` used by the commands.
- `requirements.txt` – dependencies needed to run the commands.

## Usage

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

export OPENAI_API_KEY="sk-your-key"

idxr prepare_datasets \
  --model quickstart.registry:MODEL_REGISTRY \
  --config config/prepare_datasets_config.json \
  --output-root workdir/partitions

idxr vectorize index \
  --model quickstart.registry:MODEL_REGISTRY \
  --partition-manifest workdir/partitions/manifest.json \
  --partition-out-dir workdir/chroma_partitions \
  --collection quickstart \
  --batch-size 50 \
  --resume

idxr vectorize status \
  --model quickstart.registry:MODEL_REGISTRY \
  --partition-dir workdir/partitions \
  --partition-out-dir workdir/chroma_partitions
```

The commands mirror those documented in the [Getting Started guide](../../docs/getting-started.md).
