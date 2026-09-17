"""Dataset ingestion parsers.

Parsing NEVER executes code: Python benchmark files are split on top-level
function definitions using the AST only (``ast.parse`` + source slices).

Supported formats: JSON, JSONL, CSV, raw Python files and per-item records.
Malformed rows are rejected with a structured error including the offending
row index.
"""
from __future__ import annotations

import ast
import csv
import io
import json
from typing import Any

from app.core.exceptions import ValidationError

MAX_CODE_CHARS = 300_000
MAX_ITEMS = 10_000

_FIELD_ALIASES = {
    "id": ("external_id",),
    "external_id": ("external_id",),
    "snippet_id": ("external_id",),
    "code": ("code",),
    "language": ("language",),
    "problem_statement": ("problem_statement",),
    "problem": ("problem_statement",),
    "statement": ("problem_statement",),
    "question": ("problem_statement",),
    "description": ("problem_statement",),
    "metadata": ("metadata",),
    "dataset_name": ("dataset_name",),
}


def _clean_record(raw: dict, index: int, default_dataset: str) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError(
            f"Row {index}: expected a JSON object, got {type(raw).__name__}.",
            details={"row": index},
        )
    record: dict[str, Any] = {"metadata": {}, "language": "python", "external_id": ""}
    for key, value in raw.items():
        target = None
        for alias, dest in _FIELD_ALIASES.items():
            if key.lower() == alias:
                target = dest[0]
                break
        if target is None:
            # unknown keys are kept as metadata
            if isinstance(value, (str, int, float, bool)) or value is None:
                record["metadata"][str(key)] = value
            continue
        record[target] = value

    code = record.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValidationError(f"Row {index}: missing non-empty 'code'.", details={"row": index})
    if len(code) > MAX_CODE_CHARS:
        raise ValidationError(
            f"Row {index}: code exceeds the {MAX_CODE_CHARS} character limit.",
            details={"row": index},
        )
    language = str(record.get("language") or "python").lower()
    if not language.isidentifier() or len(language) > 32:
        raise ValidationError(f"Row {index}: invalid language field.", details={"row": index})
    record["language"] = language
    problem_statement = record.get("problem_statement")
    record["problem_statement"] = problem_statement if isinstance(problem_statement, str) else ""
    if len(record["problem_statement"]) > 50_000:
        raise ValidationError(f"Row {index}: problem_statement too long.", details={"row": index})
    external_id = record.get("external_id")
    if not isinstance(external_id, str) or not external_id.strip():
        external_id = f"item_{index}"
    if len(external_id) > 255:
        raise ValidationError(f"Row {index}: id too long.", details={"row": index})
    metadata = record.get("metadata")
    record["metadata"] = metadata if isinstance(metadata, dict) else {}
    record["dataset_name"] = str(record.get("dataset_name") or default_dataset)
    record["external_id"] = external_id.strip()
    return record


def _extract_function_items(source: str) -> list[dict]:
    """Split a Python file into per-function benchmark items (AST only)."""
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ValidationError(
            f"Python file contains invalid syntax: line {exc.lineno}: {exc.msg}", code="INVALID_CODE"
        )
    items: list[dict] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        segment = ast.get_source_segment(source, node)
        if not segment:
            continue
        statement = ""
        if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
            statement = str(node.body[0].value.value).split("\n")[0][:500] if isinstance(node.body[0].value.value, str) else ""
        items.append(
            {
                "external_id": f"{node.name}_{node.lineno}",
                "code": segment,
                "language": "python",
                "problem_statement": statement or f"Function {node.name}",
                "metadata": {"function": node.name},
            }
        )
    return items


def parse_dataset_content(
    text: str,
    *,
    source_format: str,
    default_dataset: str,
) -> tuple[list[dict], int]:
    """Parse raw uploaded content into clean records.

    Returns (records, skipped). Raises ValidationError with a stable message
    when the whole payload cannot be processed.
    """
    fmt = (source_format or "jsonl").lower().lstrip(".")
    skipped = 0
    records: list[dict] = []

    if fmt in ("json",):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON document: {exc.msg}")
        if isinstance(data, dict):
            if "items" in data and isinstance(data["items"], list):
                data = data["items"]
            else:
                data = [data]
        if not isinstance(data, list):
            raise ValidationError("JSON document must be a list of items or an object with an 'items' list.")
        for index, raw in enumerate(data):
            records.append(_clean_record(raw, index, default_dataset))
    elif fmt in ("jsonl", "ndjson"):
        for index, line in enumerate(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Line {index}: invalid JSON: {exc.msg}", details={"row": index})
            records.append(_clean_record(raw, index, default_dataset))
    elif fmt in ("csv",):
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
        except csv.Error as exc:
            raise ValidationError(f"Invalid CSV: {exc}")
        if not reader.fieldnames or "code" not in [f.lower() for f in reader.fieldnames]:
            raise ValidationError("CSV must contain a column named 'code'.")
        for index, raw in enumerate(rows):
            clean = {k: v for k, v in raw.items()}
            records.append(_clean_record(clean, index, default_dataset))
    elif fmt in ("py", "python", "txt"):
        items = _extract_function_items(text)
        if not items:
            raise ValidationError(
                "No top-level function definitions found in the Python file; "
                "provide JSON/JSONL records or define functions to mutate."
            )
        records.extend(_clean_record(item, idx, default_dataset) for idx, item in enumerate(items))
    else:
        raise ValidationError(
            f"Unsupported dataset format '{source_format}'. Supported: json, jsonl, csv, py.",
            code="UNSUPPORTED_FORMAT",
        )

    if not records:
        raise ValidationError("No valid items found in the uploaded content.")
    if len(records) > MAX_ITEMS:
        raise ValidationError(f"Too many items ({len(records)}); the limit is {MAX_ITEMS} per dataset.")
    return records, skipped
