# Bundled datasets

Every supported file in this folder (`.json`, `.jsonl`, `.ndjson`, `.csv`, `.py`)
is imported into the database when the backend boots, so a fresh deployment
lists real benchmark data on the **Datasets** page instead of an empty table.
Imports are idempotent — a file whose parsed content hash already exists is
skipped, never duplicated (`BUNDLED_DATASETS_DIR`, `SEED_BUNDLED_DATASETS`).

| File | Items | Dataset name | Upstream | License |
| --- | --- | --- | --- | --- |
| `humaneval.jsonl` | 164 | `humaneval` | [OpenAI HumanEval](https://github.com/openai/human-eval) | MIT © OpenAI |
| `mbpp.jsonl` | 420 | `mbpp_sanitized` | [Google Research MBPP](https://github.com/google-research/google-research/tree/master/mbpp) (sanitized: train + validation + test) | CC-BY-4.0 © Google Research |
| `sample.jsonl` | 12 | `diffmia_sample_algorithms` | First-party mini dataset written for this project | Project license |

The two upstream corpora are the benchmarks LLMs are most commonly evaluated on,
which is exactly what this tool exists to score: a model that memorized a HumanEval
problem should show the differential-loss signature when its code is compared
against identifier-mutated equivalents.

## Item schema

Records follow the ingestion schema documented in the main README (§10):

```json
{
  "id": "humaneval_000",
  "dataset_name": "humaneval",
  "problem_statement": "Check if in given list of numbers, are any two numbers closer ...",
  "code": "from typing import List\n\n\ndef has_close_elements(...):\n    ...",
  "language": "python",
  "metadata": {"source": "openai/openai_humaneval", "task_id": "HumanEval/0", "entry_point": "has_close_elements"}
}
```

`code` is always a **complete top-level function definition** so the mutation
engine can rename identifiers with the AST. HumanEval's `code` is its prompt
plus canonical solution concatenated (the prompt alone is an unterminated
function); MBPP already ships complete solutions.

## Regenerating

```bash
# fetch both corpora and rewrite the .jsonl files above
.venv/Scripts/python scripts/import_benchmarks.py

# one corpus, or a smaller sample
.venv/Scripts/python scripts/import_benchmarks.py --source humaneval
.venv/Scripts/python scripts/import_benchmarks.py --limit 20
```

The script reads the corpora through the Hugging Face datasets server (no extra
dependencies), validates every record with `ast.parse` before writing, and
reports anything it had to skip. Restart the backend afterwards to import the
resulting files.

## Provenance

These files are verbatim conversions of the upstream releases, held to the shape
above. No benchmark content was authored or paraphrased by the importer, and the
per-item `metadata` keeps the upstream `task_id` so a score can be traced back to
the exact original problem. If you redistribute this project, keep this notice —
CC-BY-4.0 in particular requires attribution.
