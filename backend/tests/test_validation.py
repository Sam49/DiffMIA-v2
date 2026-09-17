from __future__ import annotations

import pytest

from app.core.exceptions import UnsafeInputError, ValidationError
from app.mutation.validation import PythonValidator, get_validator


def test_python_syntax_validation():
    validator = PythonValidator()
    assert validator.validate_syntax("def f(a):\n    return a\n").valid
    report = validator.validate_syntax("def f(:\n")
    assert not report.valid
    assert "line" in report.error or report.error != ""


def test_structural_equivalence_ignores_identifier_renames():
    validator = PythonValidator()
    original = "def f(x):\n    y = x + 1\n    return y"
    mutated = "def f(value):\n    result = value + 1\n    return result"
    assert validator.structural_equivalence(original, mutated)


def test_structural_equivalence_detects_control_flow_change():
    validator = PythonValidator()
    original = "def f(x):\n    return x + 1\n"
    different = "def f(x):\n    if x > 0:\n        return x + 1\n    return 0\n"
    assert not validator.structural_equivalence(original, different)


def test_structural_equivalence_detects_constant_change():
    validator = PythonValidator()
    original = "def f(x):\n    return x + 1\n"
    different = "def f(x):\n    return x + 2\n"
    assert not validator.structural_equivalence(original, different)


def test_get_validator_registry():
    assert get_validator("python").language == "python"
    with pytest.raises(ValidationError) as exc:
        get_validator("cobol")
    assert exc.value.code == "UNSUPPORTED_LANGUAGE"


def test_unsafe_input_error_for_broken_code():
    validator = PythonValidator()
    with pytest.raises(UnsafeInputError):
        validator.assert_safe_baseline("def broken(:\n")
