"""Language validators.

Validation NEVER executes the code being analysed. For Python we use
``ast.parse`` and ``compile`` — both are parse/compile-only operations and do
not run the program. ``compile`` produces bytecode without executing it.
"""
from __future__ import annotations

import ast
import dataclasses
from dataclasses import dataclass, field
from typing import Protocol

from app.core.exceptions import UnsafeInputError, ValidationError


@dataclass
class ValidationReport:
    valid: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    score: float = 1.0


class LanguageValidator(Protocol):
    language: str

    def validate_syntax(self, code: str) -> ValidationReport: ...

    def structural_equivalence(self, original: str, mutated: str) -> bool:
        """True when the two programs differ ONLY in allowed leaf identifiers."""
        ...


# ast fields whose *values* are allowed to differ between original and a
# semantically-equivalent identifier-mutation:
#  - Name.id          : variable references
#  - arg.arg          : function parameter names
ALLOWED_LEAF_DIFF = frozenset({"id", "arg"})


def _nodes_equal(a: ast.AST | list | object, b: ast.AST | list | object, ignored: frozenset[str]) -> bool:
    if isinstance(a, ast.AST) and isinstance(b, ast.AST):
        if a.__class__ is not b.__class__:
            return False
        for field_name, a_value in ast.iter_fields(a):
            b_value = getattr(b, field_name, None)
            if field_name in ignored:
                continue
            if not _nodes_equal(a_value, b_value, ignored):
                return False
        return True
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(_nodes_equal(x, y, ignored) for x, y in zip(a, b))
    # scalars / constants
    if isinstance(a, (ast.AST, list)) or isinstance(b, (ast.AST, list)):
        return False
    return a == b


class PythonValidator:
    """Validator for Python benchmark code using AST + compile only."""

    language = "python"

    def validate_syntax(self, code: str) -> ValidationReport:
        try:
            ast.parse(code, mode="exec")
        except SyntaxError as exc:  # pragma: no cover - exercised through engine paths
            return ValidationReport(valid=False, error=f"Syntax error at line {exc.lineno}: {exc.msg}")
        try:
            compile(code, "<diffmia-validation>", "exec")  # parse/compile only; never executed
        except (SyntaxError, ValueError, OverflowError) as exc:  # pragma: no cover
            return ValidationReport(valid=False, error=f"Compile error: {exc}")
        return ValidationReport(valid=True)

    def structural_equivalence(self, original: str, mutated: str) -> bool:
        try:
            orig_tree = ast.parse(original, mode="exec")
            mut_tree = ast.parse(mutated, mode="exec")
        except SyntaxError:
            return False
        return _nodes_equal(orig_tree, mut_tree, ALLOWED_LEAF_DIFF)

    def assert_safe_baseline(self, code: str) -> None:
        """Called at ingestion time; raises a structured error for bad input."""
        report = self.validate_syntax(code)
        if not report.valid:
            raise UnsafeInputError(
                f"Invalid Python code: {report.error}", details={"language": "python"}
            )


_VALIDATORS: dict[str, LanguageValidator] = {"python": PythonValidator()}


def get_validator(language: str) -> LanguageValidator:
    validator = _VALIDATORS.get(language.lower())
    if validator is None:
        raise ValidationError(
            f"Language '{language}' is not supported yet. Supported: {', '.join(sorted(_VALIDATORS))}",
            code="UNSUPPORTED_LANGUAGE",
        )
    return validator


def register_validator(language: str, validator: LanguageValidator) -> None:
    """Extension point: plug validators for additional languages."""
    _VALIDATORS[language.lower()] = validator
