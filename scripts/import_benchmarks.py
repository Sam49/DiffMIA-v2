#!/usr/bin/env python
"""Import official benchmark corpora as bundled datasets.

DiffMIA scores benchmark snippets, so the corpora it ships with should be the
real ones. This script converts the upstream releases into the project's dataset
schema (``id`` / ``dataset_name`` / ``problem_statement`` / ``code`` /
``language`` / ``metadata``) and writes them under ``datasets/``, where the
backend imports every file at boot (``SEED_BUNDLED_DATASETS``).

Sources (fetched through the Hugging Face datasets server, no SDK required):

* ``openai/openai_humaneval`` — 164 problems, MIT, © OpenAI.
  ``code`` = prompt + canonical solution, i.e. a complete function definition
  that the mutation engine can parse with the AST.
* ``google-research-datasets/mbpp`` (``sanitized``) — 427 problems,
  CC-BY-4.0, © Google Research.
* ``bigcode/bigcodebench`` (``v0.1.4``) — 1140 problems, Apache-2.0,
  © BigCode. ``code`` = ``code_prompt`` (imports + function declaration) +
  ``canonical_solution``.
* ``xlangai/DS-1000`` — 1000 data-science problems, CC-BY-SA-4.0,
  © XLang Lab (HKUNLP). Rows whose ``reference_code`` is not a top-level
  function definition (library-specific driver-only code) are counted and
  skipped, never rewritten or wrapped, so the mutation engine only ever sees
  shapes it can parse.

Usage::

    python scripts/import_benchmarks.py                # all corpora
    python scripts/import_benchmarks.py --source humaneval --limit 20
    python scripts/import_benchmarks.py --out datasets

Every record is validated with ``ast.parse`` before it is written, so a corpus
change upstream can never silently introduce code the pipeline cannot mutate.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path
from typing import Any, Iterator

ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
PAGE_SIZE = 100
RETRY_ATTEMPTS = 4

REPO_ROOT = Path(__file__).resolve().parents[1]

SOURCES: dict[str, dict[str, Any]] = {
    "humaneval": {
        "dataset": "openai/openai_humaneval",
        "config": "openai_humaneval",
        "splits": ("test",),
        "filename": "humaneval.jsonl",
        "dataset_name": "humaneval",
        "description": "OpenAI HumanEval — hand-written Python programming problems.",
        "license": "MIT © OpenAI",
    },
    "mbpp": {
        "dataset": "google-research-datasets/mbpp",
        "config": "sanitized",
        # The sanitized corpus is spread across three splits; "prompt" only
        # carries task text without solutions, so it is excluded.
        "splits": ("train", "validation", "test"),
        "filename": "mbpp.jsonl",
        "dataset_name": "mbpp_sanitized",
        "description": "Google Research MBPP (sanitized) — entry-level Python programming problems.",
        "license": "CC-BY-4.0 © Google Research",
    },
    "bigcodebench": {
        "dataset": "bigcode/bigcodebench",
        "config": "default",
        # v0.1.4 is the latest published inventory of the corpus; the earlier
        # version splits overlap it (same task_id), so only this one is used.
        "splits": ("v0.1.4",),
        "filename": "bigcodebench.jsonl",
        "dataset_name": "bigcodebench",
        "description": "BigCodeBench — practical Python tasks with diverse standard-library and third-party calls.",
        "license": "Apache-2.0 © BigCode",
    },
    "ds1000": {
        "dataset": "xlangai/DS-1000",
        "config": "default",
        "splits": ("test",),
        "filename": "ds1000.jsonl",
        "dataset_name": "ds1000",
        "description": "DS-1000 — data-science Python problems across Pandas, NumPy, SciPy and related libraries.",
        "license": "CC-BY-SA-4.0 © XLang Lab (HKUNLP)",
    },
}


def _fetch_page(source: dict[str, Any], split: str, offset: int, length: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "dataset": source["dataset"],
            "config": source["config"],
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    url = f"{ROWS_ENDPOINT}?{query}"
    last_error: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https host
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def _iter_rows(source: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield raw rows from every configured split (deduplicated by caller)."""
    for split in source["splits"]:
        offset = 0
        total: int | None = None
        while total is None or offset < total:
            page = _fetch_page(source, split, offset, PAGE_SIZE)
            total = int(page.get("num_rows_total", 0))
            rows = page.get("rows", [])
            if not rows:
                break
            for entry in rows:
                yield entry["row"]
            offset += len(rows)


def _clean_code(code: str) -> str:
    return code.replace("\r\n", "\n").strip("\n")


def _statement_from_prompt(prompt: str, fallback: str) -> str:
    """First meaningful line of the task text (HumanEval keeps it in the prompt)."""
    for line in prompt.splitlines():
        stripped = line.strip().strip('"').strip()
        if stripped and not stripped.startswith(("from ", "import ", "def ", "class ")):
            return stripped[:1000]
    return fallback


def _valid_python(code: str) -> bool:
    with warnings.catch_warnings():
        # Benchmark docstrings contain sequences like '\w', which ast.parse warns
        # about as an invalid escape. That is upstream content, not our problem.
        warnings.simplefilter("ignore", SyntaxWarning)
        try:
            ast.parse(code, mode="exec")
        except SyntaxError:
            return False
    return True


def _has_top_level_def(code: str) -> bool:
    """True when the code contains at least one top-level function definition."""
    if not _valid_python(code):
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(code, mode="exec")
    return any(isinstance(node, ast.FunctionDef) for node in tree.body)


def _humaneval_record(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    prompt = str(row.get("prompt") or "")
    solution = str(row.get("canonical_solution") or "")
    code = _clean_code(prompt + solution if solution else prompt)
    if not code or not _valid_python(code):
        return None
    task_id = str(row.get("task_id") or f"HumanEval/{index}")
    return {
        "id": f"humaneval_{index:03d}",
        "dataset_name": SOURCES["humaneval"]["dataset_name"],
        "problem_statement": _statement_from_prompt(prompt, task_id),
        "code": code,
        "language": "python",
        "metadata": {
            "source": "openai/openai_humaneval",
            "license": SOURCES["humaneval"]["license"],
            "task_id": task_id,
            "entry_point": str(row.get("entry_point") or ""),
        },
    }


def _mbpp_record(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    code = _clean_code(str(row.get("code") or ""))
    if not code or not _valid_python(code):
        return None
    task_id = row.get("task_id", index)
    return {
        "id": f"mbpp_{index:03d}",
        "dataset_name": SOURCES["mbpp"]["dataset_name"],
        "problem_statement": str(row.get("prompt") or "").strip()[:1000],
        "code": code,
        "language": "python",
        "metadata": {
            "source": "google-research-datasets/mbpp",
            "license": SOURCES["mbpp"]["license"],
            "task_id": task_id,
            "test_imports": row.get("test_imports") or [],
        },
    }


def _bigcodebench_record(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    declaration = str(row.get("code_prompt") or "")
    solution = str(row.get("canonical_solution") or "")
    # code_prompt carries imports + the `def task_func(...):` header; the
    # canonical solution is the indented body, so concatenation yields a
    # complete function definition (same convention as HumanEval).
    code = _clean_code(declaration + solution)
    if not code or not _valid_python(code):
        return None
    task_id = str(row.get("task_id") or f"BigCodeBench/{index}")
    libs_raw = row.get("libs") or []
    libs = [str(value) for value in libs_raw] if isinstance(libs_raw, (list, tuple)) else []
    return {
        "id": f"bigcodebench_{index:03d}",
        "dataset_name": SOURCES["bigcodebench"]["dataset_name"],
        "problem_statement": str(row.get("instruct_prompt") or "").strip()[:1000],
        "code": code,
        "language": "python",
        "metadata": {
            "source": "bigcode/bigcodebench",
            "license": SOURCES["bigcodebench"]["license"],
            "task_id": task_id,
            "entry_point": str(row.get("entry_point") or ""),
            "libs": libs,
        },
    }


def _ds1000_record(row: dict[str, Any], index: int) -> dict[str, Any] | None:
    code = _clean_code(str(row.get("reference_code") or ""))
    # DS-1000 reference code is often driver-only (`result = g(df, List)` with
    # the function ambiguity resolved elsewhere in the harness). A row without
    # a top-level `def` never yields a function the mutation engine can rename,
    # so it is skipped rather than reshaped.
    if not code or not _has_top_level_def(code):
        return None
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    problem_id = metadata.get("problem_id", index)
    prompt = str(row.get("prompt") or "")
    # The prompt is 'Problem: <natural language> A: <code context>'. Keep only
    # the natural-language task; the trailing code context is upstream data we
    # do not need and would otherwise truncate mid-snippet.
    statement = prompt.split("\nA:\n", 1)[0].removeprefix("Problem:").strip()
    return {
        "id": f"ds1000_{int(problem_id):04d}",
        "dataset_name": SOURCES["ds1000"]["dataset_name"],
        "problem_statement": statement[:1000],
        "code": code,
        "language": "python",
        "metadata": {
            "source": "xlangai/DS-1000",
            "license": SOURCES["ds1000"]["license"],
            "problem_id": problem_id,
            "library": str(metadata.get("library") or ""),
            "test_case_cnt": metadata.get("test_case_cnt"),
            "perturbation_type": metadata.get("perturbation_type"),
            "perturbation_origin_id": metadata.get("perturbation_origin_id"),
        },
    }


BUILDERS = {
    "humaneval": _humaneval_record,
    "mbpp": _mbpp_record,
    "bigcodebench": _bigcodebench_record,
    "ds1000": _ds1000_record,
}


def build_source(name: str, out_dir: Path, limit: int | None) -> tuple[int, int]:
    source = SOURCES[name]
    builder = BUILDERS[name]
    records: list[dict[str, Any]] = []
    skipped = 0
    seen: set[str] = set()
    for row in _iter_rows(source):
        task_key = str(row.get("task_id", ""))
        if task_key and task_key in seen:
            continue
        record = builder(row, len(records))
        if record is None:
            skipped += 1
            continue
        if task_key:
            seen.add(task_key)
        records.append(record)
        if limit is not None and len(records) >= limit:
            break

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / source["filename"]
    target.write_text(
        "".join(json.dumps(record, ensure_ascii=True) + "\n" for record in records),
        encoding="utf-8",
    )
    print(
        f"{name}: wrote {len(records)} items from splits {'+'.join(source['splits'])} "
        f"to {target if target.is_absolute() else target.relative_to(REPO_ROOT)}"
        + (f" ({skipped} skipped: unsuitable code)" if skipped else "")
    )
    return len(records), skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=[*SOURCES, "all"], default="all")
    parser.add_argument("--out", default=str(REPO_ROOT / "datasets"), help="Output directory.")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N items per corpus.")
    args = parser.parse_args(argv)

    names = list(SOURCES) if args.source == "all" else [args.source]
    out_dir = Path(args.out)
    failures = 0
    for name in names:
        try:
            build_source(name, out_dir, args.limit)
        except RuntimeError as exc:
            failures += 1
            print(f"{name}: FAILED — {exc}", file=sys.stderr)
    if failures:
        print(f"{failures} corpus/corpora failed; nothing else was changed.", file=sys.stderr)
        return 1
    print("Restart the backend (or run seed_bundled_datasets) to import the new files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
