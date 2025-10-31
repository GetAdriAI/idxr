# idxr: Model-Centric Indexing Story

**idxr** exists for teams who want a dependable, repeatable way to turn any structured dataset into a searchable vector index. Everything revolves around three pillars:

- 📚 **Documentation** – Browse the full MkDocs site at https://getadriai.github.io/idxr/ (or build it locally with `mkdocs serve`).

- **Model-centric** – you describe your world as Pydantic models, and idxr keeps schemas, partitions, and manifests aligned with those models.
- **Config-driven** – declarative JSON configs capture how each model should be prepared and indexed, so onboarding a new dataset is as easy as committing a config file.
- **Fail-stop-retry** – every stage records checkpoints, row digests, and error payloads so the pipeline halts loudly when something goes wrong and then resumes from where it stopped.

## A Day in the Life of an Index

The timeline below is an example run that demonstrates how idxr accompanies a team from the first dataset drop through ongoing maintenance.

1. **First launch (Create)**  
   You register your domain models in a registry module and run:

```bash
export MODEL_REGISTRY="my_project.registry:MODEL_REGISTRY"
idxr prepare_datasets new-config foundation --model "$MODEL_REGISTRY"
```

   idxr scaffolds a config like:

   ```json
   {
     "Contract": {
       "path": "datasets/contracts.csv",
       "columns": {
         "id": "CONTRACT_ID",
         "title": "CONTRACT_TITLE",
         "summary": "DESCRIPTION"
       },
       "delimiter": ",",
       "drop_na_columns": ["summary"]
     }
   }
   ```

   That config is committed, reviewed, and becomes the contract between data engineers and the index.

2. **Daily growth (Add records)**  
   New exports arrive. You rerun `idxr prepare_datasets` with the same config; idxr deduplicates rows using digests, appends fresh partitions, and bumps manifest timestamps. No manual cleanup, no double counting.

3. **Domain expansion (Add models)**  
   Product introduces a `SupportTicket` model. You add it to the registry, run `idxr prepare_datasets new-config support --model "$MODEL_REGISTRY" --models SupportTicket`, and drop the resulting JSON alongside the original config. idxr keeps each model’s partitions distinct but indexed in the same collection.

4. **Schema shakeups (Update models)**  
   If `Contract` gains a new field, the model registry changes first. `idxr prepare_datasets` notices, versions the schema, and marks older partitions as stale. When `idxr vectorize` runs next, it honours resume checkpoints, reindexes only what changed, and writes audit-friendly error reports for anything it had to skip.

5. **Operational guardrails**  
   During indexing, any hard failure triggers a fail-stop. idxr writes a YAML report capturing offending rows and context so you can fix the source data, then rerun `idxr vectorize --resume` to continue exactly where it left off. Optional E2E sampling produces JSON snippets you can review with stakeholders before the big push.

## Tools in the Box

- `idxr prepare_datasets` – partitions CSV/JSONL sources, heals malformed rows, maintains a manifest with digests, and generates drop plans.
- `idxr vectorize` – streams partitions into ChromaDB (local or cloud), enforces token budgets, compacts documents via OpenAI when needed, and exports structured error reports.
- Shared libraries – offer manifest helpers, truncation strategies, drop orchestration, and CLI utilities to wire everything together.

## Why idxr?

- 🔁 **Lifecycle clarity** – creation, accumulation, model expansion, and schema updates follow the same playbook.
- ✍️ **Single source of truth** – configs live in version control, so reviews and rollbacks are trivial.
- 🛑 **Predictable failure semantics** – when something breaks, the pipeline stops before corrupting data and tells you exactly what needs attention.
- 🔌 **Bring-your-own registry** – ship configs with ECC exports today, swap to CRM logs tomorrow, all with the same toolkit.
- 📦 **PyPI-ready** – install via `pip install idxr`, call the CLIs, import the libraries, and compose your own orchestration scripts.

## Querying Multi-Collection Indexes

When indexing large datasets (16M+ records), idxr distributes data across multiple ChromaDB collections using the `PartitionCollectionStrategy`. To query efficiently across these collections:

1. **Generate query config** after indexing completes:
   ```bash
   idxr vectorize generate-query-config \
     --partition-out-dir build/vector \
     --output query_config.json \
     --model "$MODEL_REGISTRY"
   ```

2. **Use the async query client** in your application:
   ```python
   from indexer.vectorize_lib.query_client import AsyncMultiCollectionQueryClient

   async with AsyncMultiCollectionQueryClient(
       config_path=Path("query_config.json"),
       client_type="cloud",
       cloud_api_key=os.getenv("CHROMA_API_TOKEN"),
   ) as client:
       # Query specific models
       results = await client.query(
           query_texts=["SAP transaction tables"],
           n_results=10,
           models=["Table", "Field"],  # Auto fan-out to relevant collections
       )
   ```

The client automatically:
- Maps model names to their collections
- Fans out queries in parallel using `asyncio`
- Merges and ranks results by distance across collections
- Handles partial failures gracefully

For complete documentation, see [`QUERYING.md`](QUERYING.md) and [`examples/query_example.py`](examples/query_example.py).

---

For deep dives and operational recipes, explore [`FAQ.md`](FAQ.md), [`DOC.md`](DOC.md), [`TRUNCATION_EXAMPLES.md`](TRUNCATION_EXAMPLES.md), [`ERROR_HANDLING.md`](ERROR_HANDLING.md), and [`QUERYING.md`](QUERYING.md).
