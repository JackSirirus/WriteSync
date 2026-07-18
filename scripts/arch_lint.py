#!/usr/bin/env python3
"""
WriteSync Architecture Linter

Scans ``src/`` for four categories of architecture violations and reports them
in ``file:line:rule`` form.

Rules
-----
1. ``NO_SCATTERED_PROMPT``     - inline prompt strings in non-prompt files
2. ``NO_DIRECT_FILE_IO``       - raw file operations outside the persistence layer
3. ``NO_MANUAL_FIELD_MAPPING`` - manual TypedDict field copying in functions
4. ``LOGGER_NAME``             - logger name must be exactly ``"writesync"``

Usage
-----
::

    python scripts/arch_lint.py
    python -m scripts.arch_lint
    from scripts.arch_lint import run_lint, LintViolation

Exit codes
----------
``0`` - no violations
``1`` - one or more violations found
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# Project root (parent of the scripts/ package).
ROOT = Path(__file__).resolve().parent.parent

# Match a CJK Unified Ideograph (basic block + extension A).
_CJK_CHAR = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# Match getLogger("...") / getLogger('...') with a non-empty string argument.
_GETLOGGER_RE = re.compile(r'getLogger\s*\(\s*["\']([^"\']+)["\']\s*\)')


# ── public types ──────────────────────────────────────────────────────────

@dataclass
class LintViolation:
    """A single architecture violation found in a source file."""
    file: str
    line: int
    rule: str
    message: str


# ── generic helpers ───────────────────────────────────────────────────────

def _walk_py_files(src_path: Path) -> list[Path]:
    """Return all ``*.py`` files under ``src_path`` in sorted order."""
    if not src_path.exists() or not src_path.is_dir():
        return []
    return sorted(p for p in src_path.rglob("*.py") if p.is_file())


def _read_text(p: Path) -> str:
    """Best-effort UTF-8 read; empty string on failure."""
    try:
        return p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def _relpath(p: Path) -> str:
    """POSIX-style path relative to the project root."""
    try:
        return str(p.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def _parse_tree(p: Path, text: str) -> ast.Module | None:
    """Parse source text; return ``None`` on syntax error."""
    try:
        return ast.parse(text, filename=str(p))
    except SyntaxError:
        return None


# ── Rule 1: NO_SCATTERED_PROMPT ───────────────────────────────────────────

def _check_scattered_prompts(src_path: Path) -> list[LintViolation]:
    """Flag any string literal >100 chars with Chinese + (ends with '?' or contains '请')."""
    violations: list[LintViolation] = []
    prompts_dir = src_path / "agents" / "prompts"
    excluded_files = {src_path / "agents" / "response_models.py"}

    for py_file in _walk_py_files(src_path):
        if py_file in excluded_files:
            continue
        if prompts_dir in py_file.parents:
            continue
        rel = _relpath(py_file)
        text = _read_text(py_file)
        if not text:
            continue
        tree = _parse_tree(py_file, text)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            s = node.value
            if len(s) <= 100:
                continue
            if not _CJK_CHAR.search(s):
                continue
            stripped = s.rstrip()
            ends_q = stripped.endswith("?") or stripped.endswith("？")
            has_qing = "请" in s
            if not (ends_q or has_qing):
                continue
            violations.append(LintViolation(
                file=rel,
                line=node.lineno,
                rule="NO_SCATTERED_PROMPT",
                message=(
                    f"Inline prompt-like string ({len(s)} chars) with Chinese + "
                    f"{'?' if ends_q else '请'} — move to src/agents/prompts/"
                ),
            ))
    return violations


# ── Rule 2: NO_DIRECT_FILE_IO ─────────────────────────────────────────────

def _classify_io_call(node: ast.Call) -> str | None:
    """Return a short tag describing the I/O call, or ``None`` if not file I/O."""
    func = node.func
    if isinstance(func, ast.Name):
        return "open()" if func.id == "open" else None
    if isinstance(func, ast.Attribute):
        attr = func.attr
        if attr in ("read_text", "write_text", "read_bytes", "write_bytes"):
            return f".{attr}()"
        if attr in ("load", "dump") and isinstance(func.value, ast.Name) and func.value.id == "json":
            return f"json.{attr}()"
    return None


def _check_direct_file_io(src_path: Path) -> list[LintViolation]:
    """Flag raw file I/O calls outside the persistence layer."""
    violations: list[LintViolation] = []
    excluded_files = {
        src_path / "state" / "persistence.py",
        src_path / "state" / "persistence_sqlite.py",
        src_path / "agents" / "context.py",
    }

    for py_file in _walk_py_files(src_path):
        if py_file in excluded_files:
            continue
        rel = _relpath(py_file)
        text = _read_text(py_file)
        if not text:
            continue
        tree = _parse_tree(py_file, text)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            tag = _classify_io_call(node)
            if tag is None:
                continue
            violations.append(LintViolation(
                file=rel,
                line=node.lineno,
                rule="NO_DIRECT_FILE_IO",
                message=f"Direct file I/O call {tag} — go through persistence layer",
            ))
    return violations


# ── Rule 3: NO_MANUAL_FIELD_MAPPING ───────────────────────────────────────

def _subscript_str_key(node: ast.Subscript) -> str | None:
    """Extract the string key from a Subscript like ``state['key']``."""
    slice_node = node.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


def _iter_function_statements(func_node: ast.AST) -> list[ast.AST]:
    """Walk a function body but skip nested function/class definitions."""
    nodes: list[ast.AST] = []
    for stmt in getattr(func_node, "body", []):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        nodes.extend(ast.walk(stmt))
    return nodes


def _check_manual_field_mapping(src_path: Path) -> list[LintViolation]:
    """Flag functions with 3+ ``target['k'] = src.k`` assignments."""
    violations: list[LintViolation] = []

    for py_file in _walk_py_files(src_path):
        rel = _relpath(py_file)
        # Rule 3 explicitly excludes tests/. (We already walk only src/,
        # but the path filter is kept defensive.)
        if rel.startswith("tests/") or rel.startswith("tests\\"):
            continue
        text = _read_text(py_file)
        if not text:
            continue
        tree = _parse_tree(py_file, text)
        if tree is None:
            continue
        for func_node in ast.walk(tree):
            if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            mapping_count = 0
            for stmt in _iter_function_statements(func_node):
                if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
                    continue
                target = stmt.targets[0]
                value = stmt.value
                if not isinstance(target, ast.Subscript):
                    continue
                key = _subscript_str_key(target)
                if key is None:
                    continue
                if not isinstance(value, ast.Attribute):
                    continue
                if key == value.attr:
                    mapping_count += 1
            if mapping_count >= 3:
                violations.append(LintViolation(
                    file=rel,
                    line=func_node.lineno,
                    rule="NO_MANUAL_FIELD_MAPPING",
                    message=(
                        f"Function '{func_node.name}' has {mapping_count} manual field "
                        f"mappings — use a registry/factory"
                    ),
                ))
    return violations


# ── Rule 4: LOGGER_NAME ───────────────────────────────────────────────────

def _check_logger_name(src_path: Path) -> list[LintViolation]:
    """Flag any ``getLogger(name)`` that is not exactly ``"writesync"``."""
    violations: list[LintViolation] = []

    for py_file in _walk_py_files(src_path):
        rel = _relpath(py_file)
        text = _read_text(py_file)
        if not text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in _GETLOGGER_RE.finditer(line):
                name = m.group(1)
                if name == "writesync":
                    continue
                violations.append(LintViolation(
                    file=rel,
                    line=lineno,
                    rule="LOGGER_NAME",
                    message=f"getLogger('{name}') should be getLogger('writesync')",
                ))
    return violations


# ── public API ────────────────────────────────────────────────────────────

def run_lint(src_dir: str = "src") -> list[LintViolation]:
    """Run all four lint rules over ``src_dir`` and return sorted violations.

    The result is sorted by ``(file, line)`` for stable output.
    """
    src_path = Path(src_dir)
    if not src_path.is_absolute():
        src_path = ROOT / src_path
    violations: list[LintViolation] = []
    violations.extend(_check_scattered_prompts(src_path))
    violations.extend(_check_direct_file_io(src_path))
    violations.extend(_check_manual_field_mapping(src_path))
    violations.extend(_check_logger_name(src_path))
    violations.sort(key=lambda v: (v.file, v.line, v.rule))
    return violations


# ── CLI entry point ───────────────────────────────────────────────────────

def _print_report(violations: list[LintViolation]) -> None:
    """Print violations grouped by file, with a summary line."""
    if not violations:
        print("All checks passed")
        return
    by_file: dict[str, list[LintViolation]] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)
    for f, vs in by_file.items():
        print(f"\n{f}:")
        for v in vs:
            print(f"  {v.line}: [{v.rule}] {v.message}")
    print(f"\n{len(violations)} violations found")


if __name__ == "__main__":
    _violations = run_lint("src")
    _print_report(_violations)
    sys.exit(1 if _violations else 0)
