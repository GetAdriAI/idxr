# Intelligent Document Truncation Examples

This guide shows how the indexer handles oversized documents using intelligent truncation strategies.

## Overview

When a document exceeds the OpenAI API token limit (8192 tokens for text-embedding-3-small/large), the indexer automatically truncates it using context-aware strategies that preserve the most important information.

## Configuration

You can configure the truncation strategy at multiple levels, with the following precedence order (highest to lowest):

### 1. Per-Model Configuration (Most Specific)

Specify different strategies for different models in your JSON config:

```json
{
  "Table": {
    "path": "tables.csv",
    "columns": {
      "id": "table_id",
      "name": "table_name",
      "description": "table_description"
    },
    "truncation_strategy": "end"
  },
  "Documentation": {
    "path": "docs.csv",
    "columns": {
      "id": "doc_id",
      "title": "title",
      "content": "content"
    },
    "truncation_strategy": "sentences"
  },
  "TechnicalSpec": {
    "path": "specs.csv",
    "columns": {
      "id": "spec_id",
      "definition": "definition"
    },
    "truncation_strategy": "middle_out"
  }
}
```

### 2. CLI Argument (Global Default)

Set a default strategy for all models via command line:

```bash
# Use 'sentences' for all models (unless overridden in config)
vectorize index --config models.json \
                --truncation-strategy sentences \
                --collection my_collection

# Available choices: end, start, middle_out, sentences, auto
```

### 3. Auto-Detection (Fallback)

When not specified, the system automatically selects the best strategy:

```bash
# Let the system decide based on model characteristics
vectorize index --config models.json \
                --truncation-strategy auto \
                --collection my_collection
```

### Configuration Examples

**Example 1: Mixed configuration**
```bash
vectorize index --config models.json --truncation-strategy middle_out
```

With `models.json`:
```json
{
  "Table": {
    "path": "tables.csv",
    "columns": {"id": "id", "description": "desc"},
    "truncation_strategy": "end"  // Overrides CLI default
  },
  "Documentation": {
    "path": "docs.csv",
    "columns": {"id": "id", "content": "content"}
    // No strategy specified, uses CLI default 'middle_out'
  }
}
```

**Example 2: All auto-detection**
```bash
vectorize index --config models.json --truncation-strategy auto
```

Each model's strategy will be automatically determined based on its characteristics.

**Example 3: No CLI argument (default is auto)**
```bash
vectorize index --config models.json --collection my_collection
```

All models will use auto-detection unless specified in the JSON config.

## How It Works

### 1. Automatic Detection

```python
# During indexing, token count is checked
token_count = count_tokens(text, encoder)

if token_count > MAX_TOKENS_PER_REQUEST:  # 8192
    # Trigger intelligent truncation with precedence:
    # 1. Per-model config
    # 2. CLI argument
    # 3. Auto-detection
    strategy = model_config.truncation_strategy or cli_default or auto_detect()

    truncated_text, final_tokens, was_truncated = truncate_text_intelligently(
        text,
        max_tokens=int(MAX_TOKENS_PER_REQUEST * 0.95),  # 7782 tokens (5% safety)
        encoder=encoder,
        strategy=strategy,
    )
```

### 2. Strategy Selection

When auto-detection is used (fallback when no configuration specified), the system chooses the best strategy based on your data:

| Model Type | Semantic Fields | Strategy | Rationale |
|------------|----------------|----------|-----------|
| Table | name, description | `end` | Table names and descriptions are at the start |
| Field | documentation, help_text | `sentences` | Maintain readability |
| Technical | parameters, config | `middle_out` | Preserve structure from both ends |
| Default | any | `middle_out` | Safest general approach |

### 3. Truncation Strategies in Detail

#### Strategy: `end`

**Purpose:** Keeps the beginning intact, truncates from the end

**Best for:**
- Tables, fields, functions where names/descriptions come first
- Schemas where structure is defined at the top
- Data where recent/later information is less critical

**How it works:**
```
Original: [HEADER][content 1][content 2]...[content N]
Result:   [HEADER][content 1][content 2]... [... truncated ...]
```

**Marker:** `\n\n[... truncated ...]\n\n` (appended at end)

**Edge cases:**
- If marker doesn't fit within token limit, truncates without marker
- Uses binary search to find maximum content that fits

**Token accounting:**
```python
# Correctly accounts for marker tokens
suffix_tokens = count_tokens(marker, encoder)
target_tokens = max_tokens - suffix_tokens
# Then fits content within target_tokens
```

---

#### Strategy: `start`

**Purpose:** Keeps the end intact, truncates from the start

**Best for:**
- Log files where recent entries are most important
- Time-series data sorted chronologically
- Documents where conclusions/results are at the end

**How it works:**
```
Original: [content 1][content 2]...[content N][FOOTER]
Result:   [... truncated ...] ...[content N-2][content N-1][FOOTER]
```

**Marker:** `[... truncated ...]\n\n` (prepended at start)

**Edge cases:**
- If marker doesn't fit within token limit, truncates without marker
- Preserves as much from the end as possible

---

#### Strategy: `middle_out`

**Purpose:** Preserves both start and end, removes middle content

**Best for:**
- Technical documentation (intro + conclusion important)
- Configuration files (header + footer metadata)
- Structured documents where boundaries matter

**How it works:**
```
Original: [HEADER][middle 1][middle 2]...[middle N][FOOTER]
Result:   [HEADER]...[content] [... truncated ...] [content]...[FOOTER]
```

**Marker:** `\n\n[... truncated ...]\n\n` (inserted in middle)

**Edge cases:**
- If marker doesn't fit, falls back to `end` strategy
- Binary search finds optimal preservation from each end
- Works even with very short text

**Algorithm:**
```python
# Find how many characters to preserve from each end
# Uses binary search on character position
target_tokens = max_tokens - marker_tokens
for mid in binary_search(0, len(text)//2):
    start_part = text[:mid]
    end_part = text[-mid:]
    if count_tokens(start_part + end_part) <= target_tokens:
        # Found the maximum we can preserve
        return start_part + marker + end_part
```

---

#### Strategy: `sentences`

**Purpose:** Maintains complete sentences for readability

**Best for:**
- Documentation and help text
- Natural language content
- User-facing descriptions

**How it works:**
```
Original: [Sentence 1.] [Sentence 2.] [Sentence 3.] ... [Sentence N.]
Result:   [Sentence 1.] [Sentence 2.] [... truncated ...] [Sentence N-1.] [Sentence N.]
```

**Marker:** `\n\n[... truncated ...]\n\n`

**Edge cases:**
- If token limit < 20, falls back to `middle_out`
- If marker doesn't fit, falls back to `middle_out`
- If < 3 sentences, falls back to `middle_out`
- Preserves complete sentences only (never cuts mid-sentence)

**Sentence detection:**
```python
# Simple splitting on period, exclamation, question mark
# Followed by space or newline
sentences = re.split(r'[.!?]+\s+', text)
```

**Fallback chain:**
```
sentences → (if too small) → middle_out → (if marker too big) → end
```

---

### 4. Fallback Behavior

All strategies have intelligent fallback mechanisms for edge cases:

| Primary Strategy | Fallback Condition | Fallback Strategy | Reason |
|-----------------|-------------------|-------------------|---------|
| `sentences` | Token limit < 20 | `middle_out` | Not enough space for sentence structure |
| `sentences` | Fewer than 3 sentences | `middle_out` | Sentence-based truncation not meaningful |
| `middle_out` | Marker >= max_tokens | `end` | Not enough space to preserve both ends |
| `end` | Marker >= max_tokens | No marker | Just truncate to fit |
| `start` | Marker >= max_tokens | No marker | Just truncate to fit |

**Example fallback scenario:**
```python
# Very small token limit (5 tokens)
text = "This is a very long document with many words"
max_tokens = 5

# Try middle_out strategy
marker = "\n\n[... truncated ...]\n\n"  # ~7 tokens in this example
# Marker doesn't fit! Fall back to end strategy

# Try end strategy
suffix = "\n\n[... truncated ...]\n\n"  # ~7 tokens
# Suffix doesn't fit! Truncate without marker

result = "This is"  # Just fit what we can (5 tokens)
```

---

### 5. Token Accounting (IMPORTANT)

**Critical bug fix:** The truncation functions now properly account for marker tokens.

**Correct approach:**
```python
# Calculate marker tokens SEPARATELY
marker_tokens = count_tokens(marker, encoder)
target_tokens = max_tokens - marker_tokens

# Find content that fits within target_tokens
content = find_content_that_fits(text, target_tokens)

# Combine for final result
truncated = content + marker
final_tokens = count_tokens(content) + marker_tokens  # Should equal actual count
```

**Previous bug (now fixed):**
```python
# ❌ WRONG: Was comparing full text+marker against max_tokens
candidate = text[:mid] + marker
if count_tokens(candidate) <= max_tokens:
    # This didn't account for marker properly
```

**Why this matters:**
- Ensures truncated documents never exceed token limits
- Provides accurate token counts in metadata
- Prevents API errors from oversized requests

---

### 6. Metadata Tracking

Truncated documents get special metadata:

```python
{
    "model_name": "Table",
    "truncated": True,
    "original_tokens": 10321,
    # ... other metadata ...
}
```

## Real-World Examples

### Example 1: Table with Long Description (10,321 tokens → 7,782 tokens)

**Original Document:**
```
MARA - Material Master General Data

This table contains the general material master data for all materials in the SAP system.
It includes comprehensive information about material types, base units of measure, material
groups, and cross-plant material status. The MARA table is central to materials management
and is referenced by numerous other tables including MARC (Plant Data for Material), MARD
(Storage Location Data for Material), and MBEW (Material Valuation).

[... 9,000+ more tokens of detailed field descriptions, usage notes, relationships,
transaction codes, historical information, integration points, authorization objects,
custom fields, notes from various implementations, troubleshooting tips, performance
considerations, archiving rules, regulatory compliance notes, and extensive technical
documentation ...]

Last updated: 2024
Related transactions: MM01, MM02, MM03, MM04, MM60
Authorization objects: M_MATE_WRK, M_MATE_BUK
```

**After `end` Strategy Truncation:**
```
MARA - Material Master General Data

This table contains the general material master data for all materials in the SAP system.
It includes comprehensive information about material types, base units of measure, material
groups, and cross-plant material status. The MARA table is central to materials management
and is referenced by numerous other tables including MARC (Plant Data for Material), MARD
(Storage Location Data for Material), and MBEW (Material Valuation).

[... ~7,500 tokens of detailed field descriptions, usage notes, relationships ...]

[... truncated ...]
```

**Metadata added:**
```json
{
  "truncated": true,
  "original_tokens": 10321,
  "truncation_strategy": "end"
}
```

**Why `end` strategy?**
- Table name and core description are at the beginning
- Most important metadata (what it is, what it does) comes first
- Later content is often repetitive details

### Example 2: Configuration Documentation (9,500 tokens → 7,782 tokens)

**Original Document:**
```
Parameter: MAX_PARALLEL_RFC_CALLS

Description: Controls the maximum number of parallel RFC calls allowed

Introduction:
This parameter is critical for managing system load and preventing resource exhaustion
in scenarios involving high-volume RFC communication between systems.

[... detailed explanation ...]

Technical Details:
[... implementation notes ...]

Best Practices:
[... configuration recommendations ...]

Troubleshooting:
[... common issues and solutions ...]

Performance Impact:
[... benchmarks and tuning ...]

Conclusion:
After implementing these recommendations, monitor the system closely for the first
week to ensure stability. Adjust the parameter value based on actual workload patterns.
```

**After `middle_out` Strategy Truncation:**
```
Parameter: MAX_PARALLEL_RFC_CALLS

Description: Controls the maximum number of parallel RFC calls allowed

Introduction:
This parameter is critical for managing system load and preventing resource exhaustion
in scenarios involving high-volume RFC communication between systems.

[... first portion preserved ...]

[... truncated ...]

[... last portion preserved ...]

Conclusion:
After implementing these recommendations, monitor the system closely for the first
week to ensure stability. Adjust the parameter value based on actual workload patterns.
```

**Metadata added:**
```json
{
  "truncated": true,
  "original_tokens": 9500,
  "truncation_strategy": "middle_out"
}
```

**Why `middle_out` strategy?**
- Introduction explains what it is
- Conclusion has implementation summary
- Middle details can be less critical
- Both header and footer context preserved

### Example 3: Help Text Documentation (8,800 tokens → 7,782 tokens)

**Original Document:**
```
How to Create a Purchase Order

Step 1: Navigate to Transaction ME21N. This transaction is the standard SAP interface
for creating purchase orders. Ensure you have proper authorization before proceeding.

Step 2: Enter vendor information. Select the vendor code from the dropdown menu or use
the search functionality to find the appropriate supplier.

[... 40 more detailed steps ...]

Step 42: Review all entries carefully before saving. Click the Save button to create
the purchase order. Note the PO number for future reference.
```

**After `sentences` Strategy Truncation:**
```
How to Create a Purchase Order

Step 1: Navigate to Transaction ME21N. This transaction is the standard SAP interface
for creating purchase orders. Ensure you have proper authorization before proceeding.

Step 2: Enter vendor information. Select the vendor code from the dropdown menu or use
the search functionality to find the appropriate supplier.

[... first 15 complete steps preserved ...]

[... middle content truncated due to length ...]

[... last 5 complete steps preserved ...]

Step 42: Review all entries carefully before saving. Click the Save button to create
the purchase order. Note the PO number for future reference.
```

**Why `sentences` strategy?**
- Maintains readability
- Complete sentences make more sense
- Beginning and end steps are most critical

## Querying Truncated Documents

### Find All Truncated Documents

```python
from chromadb import Client

client = Client()
collection = client.get_collection("ecc-std")

# Query with filter
results = collection.query(
    query_texts=["material master"],
    where={"truncated": True},
    n_results=100
)

print(f"Found {len(results['ids'][0])} truncated documents")
```

### Analyze Truncation Statistics

```python
# Get all truncated documents
results = collection.get(
    where={"truncated": True},
    include=["metadatas"]
)

# Analyze token reductions
for metadata in results['metadatas']:
    original = metadata.get('original_tokens', 0)
    # Note: final tokens not stored, but we know it's ~7782
    reduction = ((original - 7782) / original) * 100
    print(f"Document {metadata['model_name']}: {original} → ~7782 tokens ({reduction:.1f}% reduction)")
```

### Search Within Truncated Documents

```python
# Truncated documents are still fully searchable
# The embedding captures the preserved content
results = collection.query(
    query_texts=["purchase order creation steps"],
    where={"truncated": True, "model_name": "Documentation"},
    n_results=10
)

for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
    print(f"\nDocument: {meta.get('name', 'Unknown')}")
    print(f"Original tokens: {meta['original_tokens']}")
    print(f"Preview: {doc[:200]}...")
```

## Edge Case Examples

### Example 4: Very Small Token Limit (100 tokens)

**Scenario:** Document exceeds limit by small amount

**Original Document (120 tokens):**
```
Table: VBAK
Sales Document Header Data

Contains order header information including sold-to party, ship-to party,
document date, pricing date, and payment terms. Critical for order processing.
```

**After `end` Strategy:**
```
Table: VBAK
Sales Document Header Data

Contains order header information including sold-to party, ship-to party,
document date, pricing date...

[... truncated ...]
```

**Notes:**
- Even small truncations get marked in metadata
- Preserves critical table name and description
- Marker indicates content was removed

---

### Example 5: Extreme Token Limit (5 tokens)

**Scenario:** Token limit is smaller than truncation marker itself

**Original Document:**
```
This is a long document with extensive technical details about configuration.
```

**Attempted Strategy:** `middle_out` (default)

**Marker check:**
```python
marker = "\n\n[... truncated ...]\n\n"
marker_tokens = count_tokens(marker)  # ~7 tokens
max_tokens = 5

if marker_tokens >= max_tokens:
    # Marker doesn't fit! Fall back to 'end' strategy
```

**After fallback to `end` strategy:**
```python
suffix = "\n\n[... truncated ...]\n\n"  # Still ~7 tokens
suffix_tokens = count_tokens(suffix)  # ~7 tokens

if suffix_tokens >= max_tokens:
    # Suffix doesn't fit either! Truncate without marker
```

**Final Result (no marker):**
```
This is a
```

**Notes:**
- With extreme limits, markers are removed entirely
- Still respects token limit strictly
- Metadata still indicates truncation occurred

---

### Example 6: Two-Sentence Document with `sentences` Strategy

**Original Document:**
```
This table stores vendor data. It contains contact information.
```

**Attempted Strategy:** `sentences`

**Fallback logic:**
```python
sentences = split_sentences(text)  # ['This table stores vendor data.', 'It contains contact information.']
num_sentences = len(sentences)  # 2

if num_sentences < 3:
    # Not enough sentences for meaningful sentence-based truncation
    # Fall back to middle_out strategy
```

**Result:** Uses `middle_out` strategy instead

**Notes:**
- Sentence strategy requires at least 3 sentences
- Automatically falls back for edge cases
- Ensures meaningful truncation

---

### Example 7: Cascading Fallbacks

**Scenario:** `sentences` → `middle_out` → `end` → no marker

**Original:** Very short document (15 tokens) that exceeds tiny limit (8 tokens)

**Step 1:** Try `sentences` strategy
```python
if max_tokens < 20:
    # Not enough space for sentence structure
    # Fall back to middle_out
```

**Step 2:** Try `middle_out` strategy
```python
marker_tokens = 7  # marker is too big
if marker_tokens >= max_tokens:  # 7 >= 8? No, continue...
    # Actually marker does fit, try middle_out
```

**Step 3:** `middle_out` works
```
Short document [... truncated ...]
```

**Notes:**
- Multiple fallback layers ensure truncation always works
- Each strategy tries its best, then delegates to simpler strategy
- Final result always respects token limit

---

## Log Output Examples

### Successful Truncation

```
2025-10-30 15:30:45 - WARNING - indexer.vectorize_lib.indexing - Document Table:a1b2c3d4e5f67890 in Table has 10,321 tokens (exceeds API limit 8,192). Applying intelligent truncation.
2025-10-30 15:30:45 - WARNING - indexer.vectorize_lib.token_management - Document Table:a1b2c3d4e5f67890 (Table) truncated: 10321 → 7782 tokens (24.6% reduction) using strategy 'end'
2025-10-30 15:30:46 - INFO - indexer.vectorize_lib.indexing - Indexed Table batch 1 (+1 docs, 7,782 tokens, total 1) [reason=single-over-safety]
```

### Multiple Truncations in a Batch

```
2025-10-30 15:31:00 - WARNING - Document Documentation:abc123... (Documentation) truncated: 9500 → 7782 tokens (18.1% reduction) using strategy 'sentences'
2025-10-30 15:31:02 - WARNING - Document Documentation:def456... (Documentation) truncated: 8900 → 7782 tokens (12.6% reduction) using strategy 'sentences'
2025-10-30 15:31:05 - INFO - Indexed Documentation batch 1 (+2 docs, 15,564 tokens, total 2) [reason=threshold-reached]
```

## Command Line Usage

### Standard Indexing (Automatic Truncation Enabled)

```bash
# Truncation happens automatically for oversized documents
vectorize.py index \
  --model kb.std.ecc_6_0_ehp_7.registry:MODEL_REGISTRY \
  --partition-manifest build/partitions/manifest.json \
  --partition-out-dir build/vector \
  --collection ecc-std \
  --log-file logs/indexing.log
```

### Monitor Truncations During Indexing

```bash
# In another terminal, watch for truncation warnings
tail -f logs/indexing.log | grep -E "(truncated|Applying intelligent truncation)"
```

### Post-Indexing Analysis

```bash
# Count truncated documents in logs
grep -c "truncated:" logs/indexing.log

# List all models with truncations
grep "truncated:" logs/indexing.log | awk '{print $8}' | sort | uniq -c

# Average reduction percentage
grep "truncated:" logs/indexing.log | grep -oP '\d+\.\d+% reduction' | \
  awk -F'%' '{sum+=$1; count++} END {print sum/count "%"}'
```

## Advanced: Custom Truncation Strategy

If you need custom truncation logic, you can extend the `token_management.py` module:

```python
from indexer.vectorize_lib.token_management import truncate_text_intelligently

# Use specific strategy
truncated, tokens, was_truncated = truncate_text_intelligently(
    text="Your very long document...",
    max_tokens=7782,
    encoder=encoder,
    strategy="middle_out",  # Force specific strategy
    preserve_start=1000,     # Customize preservation
    preserve_end=1000,
)
```

## Best Practices

1. **Monitor truncation logs** - Track which models/documents are being truncated
2. **Adjust semantic fields** - If many documents are truncated, consider which fields to include
3. **Use metadata filters** - Query specifically for truncated vs non-truncated documents
4. **Test with samples** - Use `--e2e-test-run` to preview truncation behavior
5. **Review preserved content** - Spot-check that important information is retained

## Limitations

- **Token estimation**: Token counting is approximate; actual API tokens may vary slightly
- **Safety margin**: 5% buffer ensures we stay under limit even with slight variations
- **Binary search**: Truncation uses binary search which may take a few iterations
- **No re-expansion**: Once truncated, the full document is not stored (only in source CSV)

## FAQs

**Q: Will truncation affect search quality?**
A: Truncation preserves the most important content, so search quality is maintained for key terms. The embedding still captures semantic meaning from preserved portions.

**Q: Can I see the original document after truncation?**
A: The original is in your source CSV. The `original_tokens` metadata field tells you how much was cut.

**Q: Can I disable truncation?**
A: Currently, truncation is automatic for documents exceeding the API limit. To avoid it, pre-process your CSVs to shorten documents before indexing.

**Q: What happens if truncation fails?**
A: If truncation cannot reduce the document below the limit (shouldn't happen with binary search), the document is skipped with an error log.

**Q: Does truncation slow down indexing?**
A: Truncation adds minimal overhead (< 100ms per document). Binary search converges quickly even for large documents.

---

## Summary: Key Takeaways

### Truncation Strategies

| Strategy | Best For | Preserves | Marker | Fallback |
|----------|----------|-----------|--------|----------|
| `end` | Tables, schemas, definitions | Beginning | `[... truncated ...]` (suffix) | No marker if too small |
| `start` | Logs, time-series | End | `[... truncated ...]` (prefix) | No marker if too small |
| `middle_out` | Technical docs, configs | Both ends | `[... truncated ...]` (middle) | `end` if marker too big |
| `sentences` | Documentation, help text | Complete sentences | `[... truncated ...]` (middle) | `middle_out` if < 3 sentences |

### Critical Bug Fix (Applied)

**The `target_tokens` fix ensures markers are properly accounted for:**

```python
# ✅ CORRECT (now implemented)
marker_tokens = count_tokens(marker, encoder)
target_tokens = max_tokens - marker_tokens
content = fit_content(text, target_tokens)  # Content only
final = content + marker  # Combine
```

This prevents documents from exceeding token limits and ensures accurate token counts.

### Configuration Precedence

1. **Per-model config** (`"truncation_strategy": "end"` in JSON) - highest priority
2. **CLI argument** (`--truncation-strategy sentences`) - global default
3. **Auto-detection** (based on model name and semantic fields) - fallback

### Edge Case Handling

- **Small limits:** Removes marker if it doesn't fit
- **Few sentences:** Falls back from `sentences` to `middle_out`
- **Very small limits:** Cascades through fallbacks until one works
- **All strategies:** Guaranteed to respect token limits via binary search

### Testing Coverage

✅ 37 comprehensive tests covering:
- All 4 truncation strategies
- Token limit compliance (10, 50, 100, 200 tokens)
- Edge cases (empty text, very small limits, few sentences)
- Real-world scenarios (tables, documentation, configs)

All tests pass with strict token limit enforcement.
