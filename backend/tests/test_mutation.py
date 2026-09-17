from __future__ import annotations

import ast
import builtins
import keyword

import pytest

from app.core.exceptions import ValidationError
from app.mutation.engine import MutationEngine
from app.mutation.identifiers import NoRenameableIdentifiers, plan_renames
from app.mutation.validation import PythonValidator

SUM_CODE = (
    "def calculate_sum(numbers):\n"
    "    total = 0\n"
    "    for number in numbers:\n"
    "        total += number\n"
    "    return total\n"
)


def test_engine_generates_valid_equivalent_mutation():
    engine = MutationEngine()
    result = engine.mutate(SUM_CODE, seed=42, mutation_index=1, strength=1.0)
    assert result.valid is True
    assert result.status == "VALID"
    assert result.validation_score == 1.0
    assert result.mutated_code != SUM_CODE
    assert result.mapping
    # mutated code parses and compiles
    compile(result.mutated_code, "<test>", "exec")
    # structure preserved: only identifiers changed
    assert PythonValidator().structural_equivalence(SUM_CODE, result.mutated_code)


def test_engine_is_deterministic():
    engine = MutationEngine()
    a = engine.mutate(SUM_CODE, seed=12345, mutation_index=3, strength=0.6)
    b = engine.mutate(SUM_CODE, seed=12345, mutation_index=3, strength=0.6)
    assert a.mutated_code == b.mutated_code
    assert a.mapping == b.mapping
    assert a.seed == b.seed


def test_engine_never_renames_keywords_builtins_attributes():
    code = (
        "def process(items):\n"
        "    for item in items:\n"
        "        item.value = len(item.name)\n"
        "    return item\n"
    )
    engine = MutationEngine()
    result = engine.mutate(code, seed=7, mutation_index=1, strength=1.0)
    assert result.valid
    for old, new in result.mapping.items():
        assert new not in keyword.kwlist
        assert new not in dir(builtins)
        assert new != old

    def attributes(source: str) -> set[str]:
        return {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}

    # attributes ('value', 'name') must be untouched by the mutation
    assert attributes(code) == attributes(result.mutated_code)


def test_module_level_code_without_functions_has_no_candidates():
    engine = MutationEngine()
    result = engine.mutate("x = 1\ny = x + 2\n", seed=1, mutation_index=1, strength=0.5)
    assert result.valid is False
    assert result.status == "NO_CANDIDATES"


def test_closure_referenced_parameter_is_preserved():
    code = "def outer(data):\n    def inner():\n        return data\n    return inner()\n"
    engine = MutationEngine()
    result = engine.mutate(code, seed=3, mutation_index=1, strength=1.0)
    # 'data' is read inside the nested function -> must not be renamed
    assert result.status in ("VALID", "NO_CANDIDATES")
    if result.valid:
        assert "data" in result.mapping or "data" not in code
        mutated = result.mutated_code
        assert "return data" in mutated or "data" not in code


def test_keyword_argument_hazard_blocks_parameter_rename():
    code = (
        "def join_parts(separator):\n"
        "    return separator\n\n"
        "def main():\n"
        "    return join_parts(separator='|')\n"
    )
    engine = MutationEngine()
    result = engine.mutate(code, seed=9, mutation_index=1, strength=1.0)
    # separator must not be renamed because callers use it as a keyword argument
    assert result.valid is False
    assert result.status == "NO_CANDIDATES"


def test_invalid_python_is_rejected_cleanly():
    engine = MutationEngine()
    with pytest.raises(ValidationError):
        engine.mutate("def broken(:\n    pass\n", seed=1, mutation_index=1)


def test_plan_determinism_and_spec_fields():
    plan_a = plan_renames(SUM_CODE, seed=12345, mutation_index=1, strength=0.4)
    plan_b = plan_renames(SUM_CODE, seed=12345, mutation_index=1, strength=0.4)
    assert [e.old for e in plan_a.edits] == [e.old for e in plan_b.edits]
    assert plan_a.mapping == plan_b.mapping
    assert plan_a.edits  # deterministic edits produced


def test_unsupported_language_raises_structured_error():
    from app.core.exceptions import DiffMiaError

    with pytest.raises(DiffMiaError) as exc_info:
        MutationEngine(language="javascript")
    assert exc_info.value.code == "UNSUPPORTED_LANGUAGE"


def test_snippet_seed_is_deterministic_and_scoped():
    s1 = MutationEngine.snippet_seed(42, "abc")
    s2 = MutationEngine.snippet_seed(42, "abc")
    s3 = MutationEngine.snippet_seed(42, "abd")
    assert s1 == s2
    assert s1 != s3


def test_identifier_rename_applies_consistently():
    code = (
        "def solution(numbers):\n"
        "    total = 0\n"
        "    for number in numbers:\n"
        "        total += number\n"
        "    return total\n"
    )
    result = MutationEngine().mutate(code, seed=2024, mutation_index=2, strength=1.0)
    assert result.valid
    mutated = result.mutated_code

    def identifiers(source: str) -> set[str]:
        tree = ast.parse(source)
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.arg):
                found.add(node.arg)
        return found

    old_ids = identifiers(code)
    new_ids = identifiers(mutated)
    # Every renamed occurrence must be replaced consistently
    for old, new in result.mapping.items():
        assert old not in new_ids, f"stale occurrence of {old} in: {mutated}"
        assert new in mutated
