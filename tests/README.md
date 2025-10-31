# Test Suite for Query Configuration and Async Query Client

This directory contains comprehensive tests for the multi-collection querying functionality.

## Test Coverage

### ✅ Query Configuration Tests (`test_query_config.py`)

**18 tests covering:**

1. **Config Generation:**
   - Empty directories
   - Populated partitions with multiple models
   - Writing config to file
   - Collection prefix handling

2. **Config Loading:**
   - Loading from file
   - Missing file errors
   - Invalid JSON errors
   - Missing required keys validation

3. **Model-to-Collection Mapping:**
   - Specific model queries
   - All model queries
   - Unknown model handling
   - Mixed known/unknown models

4. **Edge Cases:**
   - Malformed resume state files
   - Non-dict resume data
   - Invalid model state data
   - Collection sorting
   - Non-existent directories
   - File instead of directory

5. **Data Filtering:**
   - Models with 0 documents (excluded)
   - Models not started (excluded)
   - Valid models across multiple partitions

### ✅ Async Query Client Tests (`test_query_client.py`)

**20 tests covering:**

1. **Client Initialization:**
   - HTTP client setup
   - Cloud client setup
   - Configuration validation

2. **Connection Management:**
   - Connect/disconnect lifecycle
   - Async context manager
   - Config loading on connect
   - Collection caching

3. **Query Operations:**
   - Query specific models
   - Query all models (models=None)
   - Multiple query texts (batch queries)
   - Metadata filtering
   - Unknown model handling
   - Result merging and sorting by distance

4. **Get Operations:**
   - Get documents by ID
   - Get with metadata filters
   - Unknown model handling

5. **Count Operations:**
   - Count specific models
   - Count all documents

6. **Error Handling:**
   - Query without connection raises error
   - Query without texts/embeddings raises error
   - HTTP without host raises error
   - Cloud without API key raises error
   - Invalid client type raises error
   - Partial collection failures (graceful degradation)

7. **Performance:**
   - Collection caching verification
   - Parallel query execution (via mocks)

## Running Tests

### Run All Tests
```bash
python -m pytest tests/ -v
```

### Run Specific Test File
```bash
python -m pytest tests/test_query_config.py -v
python -m pytest tests/test_query_client.py -v
```

### Run Specific Test
```bash
python -m pytest tests/test_query_config.py::test_generate_query_config_with_data -v
```

### Run with Coverage
```bash
pip install pytest-cov
python -m pytest tests/ --cov=indexer.vectorize_lib --cov-report=html
```

## Test Results Summary

**Total: 38 tests**
- ✅ 38 passed
- ❌ 0 failed
- ⏭️ 0 skipped

**Execution Time:** ~2.5 seconds

## Test Fixtures

### `temp_partition_dir`
Creates a temporary partition output directory structure for testing.

### `populated_partition_dir`
Creates a partition directory with mock resume state files containing:
- 3 partitions
- 3 models (Table, Field, Domain)
- Various document counts
- Edge cases (empty models, not started models)

### `query_config_data`
Sample query configuration data with:
- 3 models
- 3 collections
- Model-to-collection mappings
- Collection-to-model mappings

### `query_config_file`
Temporary file containing query config JSON.

### `mock_chroma_client`
Mock ChromaDB async client with:
- Collection retrieval
- Query operations
- Get operations
- Count operations
- Configurable responses

## Test Methodology

### Unit Testing Approach
- **Isolation:** Each test is independent and uses temporary directories
- **Mocking:** ChromaDB client is mocked to avoid external dependencies
- **Fixtures:** Reusable test data and setup via pytest fixtures
- **Async Support:** Full async/await testing with pytest-asyncio

### What's Tested
✅ Config generation from resume states
✅ Model-to-collection mapping
✅ Collection-to-model reverse mapping
✅ Async query fan-out
✅ Result merging and ranking
✅ Metadata filtering pass-through
✅ Error handling and validation
✅ Collection caching
✅ Partial failure resilience

### What's Not Tested (By Design)
- Actual ChromaDB server connections (mocked)
- OpenAI API calls (not part of query client)
- Network reliability (tested via mocks)
- Real embedding generation (mocked)

## Continuous Integration

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest pytest-asyncio
      - name: Run tests
        run: pytest tests/ -v
```

## Extending Tests

### Adding New Tests

1. **For query_config.py:**
   ```python
   def test_your_new_feature(populated_partition_dir):
       config = generate_query_config(populated_partition_dir)
       assert config["something"] == expected_value
   ```

2. **For query_client.py:**
   ```python
   @pytest.mark.asyncio
   async def test_your_async_feature(query_config_file, mock_chroma_client):
       with patch("chromadb.AsyncHttpClient", return_value=mock_chroma_client):
           async with AsyncMultiCollectionQueryClient(...) as client:
               result = await client.your_method()
               assert result == expected
   ```

## Test Data

### Resume State File Structure
```json
{
  "ModelName": {
    "started": true,
    "complete": true,
    "collection_count": 1000,
    "documents_indexed": 1000,
    "indexed_at": "2025-10-31T10:00:00",
    "row_index": 1000,
    "source_signature": {...}
  }
}
```

### Query Config Structure
```json
{
  "model_to_collections": {
    "ModelName": {
      "collections": ["partition_00001"],
      "total_documents": 1000,
      "partitions": ["partition_00001"]
    }
  },
  "collection_to_models": {
    "partition_00001": ["ModelName"]
  },
  "metadata": {
    "total_collections": 1,
    "total_models": 1,
    "generated_at": "2025-10-31T12:00:00"
  }
}
```

## Debugging Tests

### View Detailed Output
```bash
python -m pytest tests/ -vv -s
```

### Run Only Failed Tests
```bash
python -m pytest tests/ --lf
```

### Stop on First Failure
```bash
python -m pytest tests/ -x
```

### Debug Specific Test
```bash
python -m pytest tests/test_query_client.py::test_query_specific_models -vv -s
```

## Dependencies

Required packages:
- `pytest>=8.0`
- `pytest-asyncio>=1.2`
- `chromadb` (for type hints, mocked in tests)

Install with:
```bash
pip install pytest pytest-asyncio
```

## Notes

- Tests use temporary directories that are automatically cleaned up
- Mock ChromaDB clients simulate realistic responses
- All async operations are properly tested with pytest-asyncio
- Tests verify both success cases and error conditions
- Collection caching is verified to ensure performance optimization works
