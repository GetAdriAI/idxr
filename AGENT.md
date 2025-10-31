The code in indexer package provides a "model" centric, config driven approach to managing the lifecycle of vector index. Broadly, we have enabled the following steps in the lifecycle of indexing: 1. Create first index with some initial records 2. Add more records to existing index 3. Add new models to existing index 4. Update index when one or models are modified

The program allows parallelization at partition level using `ThreadPoolExecutor`. Hence, writing thread-safe code is critically important.

The vectorization process follows "fail and stop and maybe retry" at partition level i.e. if a partition fails, the processing of that partition stops. Depending on the cause of failure, a partition is retried again after all other work is completed.

You can read the usage details in indexer/DOC.md or indexer/README.md.

We need to improve the logic of `poetry run python -m indexer.vectorize status ...` such that it can paint a more accurate picture.

As-Is behavior: It shows "ERRORED" if `errors` directory exist.
To-Be behavior: It should turn "ERRORED" back to "STARTED" if the current row index in the manifest file has crossed the maximum row number across all error YAML files in errors directory. Becuase this implies that the user has resumed the run and the run has progressed without erroring out again.