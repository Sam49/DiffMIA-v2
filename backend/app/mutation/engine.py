"""Deterministic mutation engine (identifier renaming strategy).

Pipeline (per spec):

    Source Code -> Parse AST -> Identify renameable identifiers ->
    Generate rename mapping -> Apply transformation -> Parse transformed code
    -> Validate AST -> Validate compilation -> Return mutation

If a mutation fails validation it is discarded and regenerated (up to
``max_attempts``). Generation is fully deterministic: (code, seed, index)
always produce the same result, so experiments are reproducible.

Distinctness: callers pass the variants already generated for a snippet via
``avoid``. Snippets with few renameable identifiers would otherwise yield the
*same* text for several mutation indices, which double-counts one piece of
evidence in the differential comparison. The retry ladder is reused to look for
a different variant; if none exists the result is reported as ``DUPLICATE``
rather than silently counted as an independent mutation.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from app.core.exceptions import ValidationError
from app.mutation.identifiers import NoRenameableIdentifiers, RenameEdit, plan_renames
from app.mutation.validation import get_validator


@dataclass
class MutationResult:
    seed: int
    mutation_index: int
    original_code: str
    mutated_code: str
    language: str
    mapping: dict[str, str] = field(default_factory=dict)
    valid: bool = False
    attempts: int = 0
    validation_score: float = 0.0
    status: str = "VALID"  # VALID | INVALID | NO_CANDIDATES | DUPLICATE
    error: str = ""


class _SourceMap:
    """Map AST line/col spans back to string offsets."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.line_offsets: list[int] = []
        offset = 0
        for line in source.splitlines(keepends=True):
            self.line_offsets.append(offset)
            offset += len(line)

    def slice(self, line: int, col: int, end_line: int, end_col: int) -> str:
        start = self.line_offsets[line - 1] + col
        if end_line == line:
            end = self.line_offsets[line - 1] + end_col
        else:
            # fall back to safe computation with keepends text
            parts = self.source.splitlines(keepends=True)
            end = sum(len(p) for p in parts[: end_line - 1]) + end_col
        return self.source[start:end]


def _apply_edits(source: str, edits: list[RenameEdit]) -> tuple[str, int]:
    """Apply edits (source order). Returns (mutated_source, applied_count).

    Spans whose sliced text does not exactly match the expected identifier are
    skipped defensively (they cannot be renamed safely).
    """
    span = _SourceMap(source)
    ordered = sorted(edits, key=lambda e: (e.line, e.col))
    chunks: list[str] = []
    cursor = 0
    applied = 0
    for edit in ordered:
        start = span.line_offsets[edit.line - 1] + edit.col
        if edit.line != edit.end_line:  # pragma: no cover - identifiers never span lines
            continue
        end = span.line_offsets[edit.line - 1] + edit.end_col
        if start < cursor:
            continue  # overlapping span -> skip (should not happen)
        if source[start:end] != edit.old:
            continue
        chunks.append(source[cursor:start])
        chunks.append(edit.new)
        cursor = end
        edit.applied = True
        applied += 1
    chunks.append(source[cursor:])
    return "".join(chunks), applied


class MutationEngine:
    def __init__(self, *, language: str = "python", max_attempts: int = 10) -> None:
        self.language = language
        self.max_attempts = max_attempts
        self.validator = get_validator(language)

    def mutate(
        self,
        code: str,
        *,
        seed: int,
        mutation_index: int,
        strength: float = 0.3,
        preserve: set[str] | None = None,
        avoid: set[str] | None = None,
    ) -> MutationResult:
        """Generate the ``mutation_index``-th mutation for ``code``.

        ``avoid`` holds variants already produced for this snippet; the engine
        retries (deterministically) to find a text outside that set so each
        mutation index contributes distinct evidence.
        """
        if self.language != "python":
            raise ValidationError(
                f"Mutation strategy 'identifier_rename' supports python only, got '{self.language}'",
                code="UNSUPPORTED_LANGUAGE",
            )
        baseline = self.validator.validate_syntax(code)
        if not baseline.valid:
            raise ValidationError(f"Cannot mutate invalid code: {baseline.error}", code="INVALID_CODE")

        avoid = set(avoid or ())
        result = MutationResult(
            seed=seed, mutation_index=mutation_index, original_code=code,
            mutated_code=code, language=self.language,
        )
        duplicate_code: str | None = None
        duplicate_mapping: dict[str, str] = {}
        duplicate_score = 0.0
        for attempt in range(self.max_attempts):
            attempt_seed = seed + attempt  # deterministic retry ladder
            try:
                plan = plan_renames(
                    code, seed=attempt_seed, mutation_index=mutation_index,
                    strength=strength, preserve=preserve,
                )
            except NoRenameableIdentifiers as exc:
                result.status = "NO_CANDIDATES"
                result.error = str(exc)
                result.attempts = attempt + 1
                return result
            except ValueError as exc:
                result.status = "INVALID"
                result.error = str(exc)
                result.attempts = attempt + 1
                return result

            mutated, applied = _apply_edits(code, plan.edits)
            result.attempts = attempt + 1
            if applied == 0:
                continue

            score = applied / len(plan.edits)
            if mutated != code and self.validator.validate_syntax(mutated).valid:
                if self.validator.structural_equivalence(code, mutated):
                    if mutated not in avoid:
                        result.mutated_code = mutated
                        result.mapping = plan.mapping
                        result.valid = True
                        result.status = "VALID"
                        result.validation_score = score
                        return result
                    # Valid, but identical to an earlier mutation of this snippet:
                    # remember it and keep looking for distinct evidence.
                    duplicate_code = mutated
                    duplicate_mapping = plan.mapping
                    duplicate_score = score
            # fall through: invalid/duplicate mutation -> retry with the next seed

        if duplicate_code is not None:
            result.mutated_code = duplicate_code
            result.mapping = duplicate_mapping
            result.status = "DUPLICATE"
            result.validation_score = duplicate_score
            result.error = (
                "Only one distinct identifier-renamed variant exists for this snippet; "
                f"it repeats an earlier mutation after {self.max_attempts} attempts."
            )
            return result

        result.status = "INVALID"
        result.error = f"Could not produce a valid mutation after {self.max_attempts} attempts"
        return result

    @staticmethod
    def snippet_seed(base_seed: int, content_hash: str) -> int:
        """Deterministic per-snippet seed derived from the experiment seed."""
        import hashlib

        digest = hashlib.sha256(f"{base_seed}:{content_hash}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % (2**31)
