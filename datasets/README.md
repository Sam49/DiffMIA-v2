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
| `bigcodebench.jsonl` | 1140 | `bigcodebench` | [BigCodeBench](https://github.com/bigcode-project/bigcodebench) (v0.1.4) | Apache-2.0 © BigCode |
| `ds1000.jsonl` | 323 | `ds1000` | [DS-1000](https://github.com/xlang-ai/DS-1000) (rows with def-shaped reference code) | CC-BY-SA-4.0 © XLang Lab (HKUNLP) |
| `sample.jsonl` | 12 | `diffmia_sample_algorithms` | First-party mini dataset written for this project | Project license |

The upstream corpora are the benchmarks LLMs are most commonly evaluated on,
which is exactly what this tool exists to score: a model that memorized a HumanEval
problem should show the differential-loss signature when its code is compared
against identifier-mutated equivalents.

The two newest corpora deliberately widen what is scored:

* **BigCodeBench** exercises realistic, tool-heavy code (many standard-library
  and third-party calls per function), the shape a model sees when it has been
  trained on practical code rather than puzzles.
* **DS-1000** is data-science code derived from StackOverflow-style problems —
  text that sits *inside* common pretraining corpora, which makes it a natural
  contamination target. Its `reference_code` is function-shaped (`def g(...):
  ...`) for 323 of the 1000 rows; the remaining rows are driver-only snippets
  (e.g. `result = np.percentile(a, p)`) that the mutation engine could not
  rename without reshaping the code, so they are skipped — never rewritten.
  Those counts are upstream properties, not editorial choices.

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

```json
{
  "id": "bigcodebench_000",
  "dataset_name": "bigcodebench",
  "problem_statement": "Calculates the average of the sums of absolute differences ...",
  "code": "import itertools\nfrom random import shuffle\ndef task_func(numbers=list(range(1, 3))):\n    ...",
  "language": "python",
  "metadata": {"source": "bigcode/bigcodebench", "license": "Apache-2.0 © BigCode", "task_id": "BigCodeBench/0", "entry_point": "task_func", "libs": ["itertools", "random"]}
}
```

DS-1000 items carry the library and perturbation metadata instead of an entry
point (`problem_id`, `library`, `perturbation_type`), and their task id maps
back to the upstream `problem_id`.

`code` is always a **complete top-level function definition** so the mutation
engine can rename identifiers with the AST. HumanEval's `code` is its prompt
plus canonical solution concatenated (the prompt alone is an unterminated
function); MBPP and DS-1000 already ship complete solutions; BigCodeBench's
`code` is its `code_prompt` (imports + function declaration) plus
`canonical_solution` (the indented body).

## Regenerating

```bash
# fetch all corpora and rewrite the .jsonl files above
.venv/Scripts/python scripts/import_benchmarks.py

# one corpus, or a smaller sample
.venv/Scripts/python scripts/import_benchmarks.py --source bigcodebench
.venv/Scripts/python scripts/import_benchmarks.py --source ds1000
.venv/Scripts/python scripts/import_benchmarks.py --limit 20
```

The script reads the corpora through the Hugging Face datasets server (no extra
dependencies), validates every record with `ast.parse` before writing, and
reports anything it had to skip. Restart the backend afterwards to import the
resulting files.

## Provenance

These files are verbatim conversions of the upstream releases, held to the shape
above. No benchmark content was authored or paraphrased by the importer; the
only curation is skipping individual records whose code is not AST-valid or
lacks a top-level function definition. The per-item `metadata` keeps the
upstream task id so a score can be traced back to the exact original problem.
If you redistribute this project, keep this notice — CC-BY-4.0 and
CC-BY-SA-4.0 in particular require attribution.
