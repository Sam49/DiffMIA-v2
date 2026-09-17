"""Conservative identifier analysis used by the mutation engine.

Renaming strategy
-----------------
Only names *bound inside a function body* (parameters, local assignments,
for-loop targets, with/except bindings, walrus targets) are candidates. Their
uses are renamed within the same function only. The following are NEVER
renamed:

* Python keywords and built-in names
* Module-level def/class names (external entry points stay stable)
* Imported module / aliased names
* Attribute names (``obj.attr``), keyword arguments (``f(x=1)``)
* Identifiers inside strings, comments or docstrings (never visited)
* Magic methods / dunder names (they are attributes or def names)
* Names referenced by a nested function/lambda/class (closure hazard)
* Names whose bound value is read through ``global``/``nonlocal``
* Parameter names that appear as a keyword argument anywhere in the module
  (renaming would silently break ``f(x=1)`` call sites)

A name is additionally only renamed when the *new* identifier does not occur
anywhere in the whole module, which prevents accidental shadowing.

Everything is deterministic: the same (source, seed, mutation index) always
yields the same mutations.
"""
from __future__ import annotations

import ast
import builtins
import hashlib
import keyword
import random
from dataclasses import dataclass, field

RESERVED_NAMES = frozenset(keyword.kwlist) | frozenset(dir(builtins))

NEW_NAME_WORDS = [
    "value", "item", "data", "result", "acc", "elem", "component", "entity",
    "arg", "param", "tmp", "buffer", "cursor", "entry", "record", "payload",
    "token", "chunk", "holder", "field", "source_val", "carrier",
]

NESTED_DEF_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
COMP_TYPES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


class NoRenameableIdentifiers(Exception):
    """Raised when the code exposes no safe identifier to rename."""


@dataclass
class RenameEdit:
    """A single identifier occurrence, addressed by line/column spans."""

    line: int
    col: int
    end_line: int
    end_col: int
    old: str
    new: str
    applied: bool = False


@dataclass
class RenamePlan:
    mapping: dict[str, str] = field(default_factory=dict)
    edits: list[RenameEdit] = field(default_factory=list)


def _sha_int(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def module_identifier_set(tree: ast.AST) -> set[str]:
    """Every identifier-like token in the module (used to avoid shadowing)."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
    return names


def _comp_shadow_names(comp: ast.AST) -> set[str]:
    """Targets bound by a comprehension's own generator clauses."""
    shadow: set[str] = set()
    for gen in comp.generators:  # type: ignore[attr-defined]
        targets = gen.target if isinstance(gen.target, ast.Name) else (
            [t for t in ast.walk(gen.target) if isinstance(t, ast.Name)] if gen.target is not None else []
        )
        if isinstance(targets, ast.Name):
            shadow.add(targets.id)
        else:
            shadow.update(t.id for t in targets if isinstance(t, ast.Name))
    return shadow


def _iter_subtree(node: ast.AST) -> ast.AST:
    """Iterate a node plus descendants, never entering nested definitions."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, NESTED_DEF_TYPES):
            continue
        yield from _iter_subtree(child)


def _iter_comprehensions(body: list[ast.stmt]) -> list[ast.AST]:
    comps: list[ast.AST] = []
    for stmt in body:
        for node in _iter_subtree(stmt):
            if isinstance(node, COMP_TYPES):
                comps.append(node)
    return comps


def _collect_nested_defs(body: list[ast.stmt]) -> list[ast.AST]:
    defs: list[ast.AST] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, NESTED_DEF_TYPES):
                defs.append(node)
    return defs


def _contains_outer_load(node: ast.AST, name: str) -> bool:
    """True if the nested definition reads ``name`` (or declares it global/nonlocal)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load) and sub.id == name:
            return True
        if isinstance(sub, (ast.Global, ast.Nonlocal)) and name in sub.names:
            return True
    return False


def _function_global_decls(body: list[ast.stmt]) -> set[str]:
    """global/nonlocal declarations in the function's own body scope."""
    names: set[str] = set()
    for stmt in body:
        for node in _iter_subtree(stmt):
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                names.update(node.names)
    return names


def _signature_args(fn: ast.AST) -> dict[str, list[ast.arg]]:
    """Map parameter name -> its ast.arg node(s) (for binding-site edits)."""
    by_name: dict[str, list[ast.arg]] = {}
    args = fn.args  # type: ignore[attr-defined]
    groups = [list(args.posonlyargs), list(args.args), list(args.kwonlyargs)]
    if args.vararg is not None:
        groups.append([args.vararg])
    if args.kwarg is not None:
        groups.append([args.kwarg])
    for group in groups:
        for arg in group:
            by_name.setdefault(arg.arg, []).append(arg)
    return by_name


def _function_candidates(fn: ast.AST) -> list[str]:
    """Bound names inside one function body, in deterministic order.

    Parameters first, then assignment-like targets in source order.
    Comprehension targets are excluded (they bind in the comprehension scope).
    Except-handler names are excluded (their span cannot be mapped safely).
    """
    candidates: list[str] = []

    def push(name: str) -> None:
        if name and name not in candidates:
            candidates.append(name)

    for name in _signature_args(fn):
        push(name)

    comp_targets: set[int] = set()
    for comp in _iter_comprehensions(fn.body):  # type: ignore[attr-defined]
        for gen in comp.generators:  # type: ignore[attr-defined]
            for node in ast.walk(gen.target):
                if isinstance(node, ast.Name):
                    comp_targets.add(id(node))

    for stmt in fn.body:  # type: ignore[attr-defined]
        for node in _iter_subtree(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                if id(node) not in comp_targets:
                    push(node.id)
    return candidates


def _iter_occurrences(body: list[ast.stmt], name: str, shadows: list[tuple[ast.AST, set[str]]]):
    """Yield AST nodes that reference ``name`` inside the function body.

    Stops at nested definitions and skips comprehensions where ``name`` is
    shadowed by a comprehension target (its occurrences there refer to the
    comprehension-local binding, not the outer one).
    """
    for stmt in body:
        yield from _occurrences_in_node(stmt, name, shadows)


def _occurrences_in_node(node: ast.AST, name: str, shadows: list[tuple[ast.AST, set[str]]]) -> ast.AST:
    if isinstance(node, NESTED_DEF_TYPES):
        return
    if isinstance(node, COMP_TYPES):
        for comp, shadow in shadows:
            if comp is node and name in shadow:
                return
        # load inside a comprehension body refers to the enclosing function's
        # binding when not shadowed -> keep descending.
    if isinstance(node, ast.Name) and node.id == name:
        yield node
    elif isinstance(node, ast.arg) and node.arg == name:
        yield node
    for child in ast.iter_child_nodes(node):
        yield from _occurrences_in_node(child, name, shadows)


def plan_renames(
    code: str,
    *,
    seed: int,
    mutation_index: int,
    strength: float = 0.3,
    preserve: set[str] | None = None,
) -> RenamePlan:
    """Plan deterministic identifier renames for ``code``.

    Raises NoRenameableIdentifiers when no safe candidate exists.
    """
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise ValueError(f"Invalid Python source: {exc}")

    preserve = set(preserve or {"self", "cls"})
    forbidden: set[str] = set(RESERVED_NAMES) | module_identifier_set(tree) | preserve

    # Name -> kwarg usage anywhere in module (breaks rename of params)
    kwarg_names: set[str] = {kw.arg for kw in ast.walk(tree) if isinstance(kw, ast.keyword) and kw.arg}

    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    functions.sort(key=lambda f: (f.lineno, f.col_offset))

    plan = RenamePlan()
    chosen_new: set[str] = set()

    for fn in functions:
        nested_defs = _collect_nested_defs(fn.body)  # type: ignore[attr-defined]
        global_decls = _function_global_decls(fn.body)  # type: ignore[attr-defined]
        comps = _iter_comprehensions(fn.body)  # type: ignore[attr-defined]
        comp_shadows = [(c, _comp_shadow_names(c)) for c in comps]
        signature_args = _signature_args(fn)

        candidates: list[str] = []
        for name in _function_candidates(fn):
            if name in RESERVED_NAMES:
                continue
            if name in preserve:
                continue
            if name in global_decls:
                continue
            if name in kwarg_names:
                continue
            if any(_contains_outer_load(d, name) for d in nested_defs):
                continue
            candidates.append(name)

        if not candidates:
            continue

        rng = random.Random(_sha_int(f"{seed}:{mutation_index}:{fn.lineno}:{fn.col_offset}"))
        rename_count = max(1, min(len(candidates), round(len(candidates) * strength)))
        rng.shuffle(candidates)
        selected = candidates[:rename_count]

        for old in selected:
            new_name = _pick_new_name(rng, old, forbidden | chosen_new)
            forbidden.add(new_name)
            chosen_new.add(new_name)
            plan.mapping[old] = new_name
            # 1) rename the parameter binding site(s) in the signature
            for arg_node in signature_args.get(old, []):
                plan.edits.append(
                    RenameEdit(
                        line=arg_node.lineno,
                        col=arg_node.col_offset,
                        end_line=arg_node.end_lineno or arg_node.lineno,
                        end_col=arg_node.end_col_offset or arg_node.col_offset,
                        old=old,
                        new=new_name,
                    )
                )
            # 2) rename every use inside the function body
            for node in _iter_occurrences(fn.body, old, comp_shadows):  # type: ignore[attr-defined]
                plan.edits.append(
                    RenameEdit(
                        line=node.lineno,
                        col=node.col_offset,
                        end_line=node.end_lineno or node.lineno,
                        end_col=node.end_col_offset or node.col_offset,
                        old=old,
                        new=new_name,
                    )
                )

    if not plan.edits:
        raise NoRenameableIdentifiers(
            "No safe renameable identifiers found (function-scope names only, "
            "keywords/imports/attributes/closure-referenced names preserved)."
        )
    return plan


def _pick_new_name(rng: random.Random, old: str, forbidden: set[str]) -> str:
    """Deterministic, collision-free replacement identifier."""
    start = rng.randrange(len(NEW_NAME_WORDS))
    words = NEW_NAME_WORDS[start:] + NEW_NAME_WORDS[:start]
    for word in words:
        candidate = word
        suffix = 1
        while candidate in forbidden or candidate == old:
            candidate = f"{word}{suffix}"
            suffix += 1
        return candidate
    # Practically unreachable; defensive fallback
    suffix = 1
    while True:
        candidate = f"x{suffix}"
        if candidate not in forbidden and candidate != old:
            return candidate
        suffix += 1

