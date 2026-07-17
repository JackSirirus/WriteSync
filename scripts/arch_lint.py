#!/usr/bin/env python3
"""
WriteSync Architecture Lint (Phase 7)

Standalone script that validates architecture constraints.
Run from the project root:  python scripts/arch_lint.py
Exit code 0 = all checks passed. Non-zero = violations found.

Checks:
  1. No hardcoded system prompts outside src/agents/prompts/
  2. No direct file I/O outside src/state/persistence*.py
  3. All logger names use lowercase "writesync"
  4. All agent modules from adapters.AGENT_MAP are in AGENT_REGISTRY
  5. WriteSyncState uses @dataclass decorator
"""

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


# ── utilities ──────────────────────────────────────────────────────────────
def _walk_py_files(path: Path):
    """Yield all .py file paths under a directory."""
    return sorted(path.rglob("*.py"))


def _read_lines(filepath: Path):
    try:
        return filepath.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return []


def _resolve_relative_import(import_path: str, base_dir: Path) -> Path:
    """Resolve a relative Python import like '..agents.character' to a file path."""
    parts = import_path.lstrip(".").split(".")
    # count dots for parent dirs
    dots = len(import_path) - len(import_path.lstrip("."))
    current = base_dir
    for _ in range(dots - 1):
        current = current.parent
    return current / Path(*parts).with_suffix(".py")


# ── check implementations ──────────────────────────────────────────────────

def check_hardcoded_prompts() -> tuple[bool, list[str]]:
    """Check 1: no hardcoded system prompt strings outside src/agents/prompts/."""
    violations = []
    prompts_dir = SRC / "agents" / "prompts"
    zh_pattern = re.compile(r"你是一个")
    en_pattern = re.compile(r"You are an?\b")
    excluded = {"arch_lint.py"}  # this file itself

    for py_file in _walk_py_files(SRC):
        if py_file.name in excluded:
            continue
        # Skip files inside prompts/
        if prompts_dir in py_file.parents:
            continue
        lines = _read_lines(py_file)
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # skip comments and docstrings (simple heuristic)
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            if zh_pattern.search(stripped) or en_pattern.search(stripped):
                # Only flag if it looks like a prompt (not a test or comment)
                violations.append(f"{py_file.relative_to(ROOT)}:{i}: {stripped[:80]}")
                break  # one violation per file is enough
    return (len(violations) == 0, violations)


def check_file_io() -> tuple[bool, list[str]]:
    """Check 2: no direct file I/O outside src/state/persistence*.py."""
    violations = []
    open_pattern = re.compile(r"\bopen\s*\(")
    path_write = re.compile(r"Path\s*\(.*\)\s*\.\s*write")
    excluded = {"arch_lint.py"}
    # Operational files that legitimately do file I/O
    allowed_io = {
        "src/utils/export.py",
        "src/utils/export_json.py",
        "src/utils/export_html.py",
        "src/utils/usage_tracker.py",
        "src/utils/doc_importer.py",
        "src/web/app.py",
        "src/orchestrator/workspace.py",
        # Data-file loaders (read project-local JSON files)
        "src/agents/fact_ledger.py",
        "src/agents/foreshadow.py",
        "src/agents/item_ledger.py",
        "src/agents/references.py",
        "src/agents/state_table.py",
        "src/agents/timeline.py",
        "src/agents/writing_rules.py",
        # Migration utility
        "src/state/migrate_to_sqlite.py",
    }

    for py_file in _walk_py_files(SRC):
        if py_file.name in excluded:
            continue
        rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
        # Allow persistence files
        if "src/state/persistence" in rel:
            continue
        # Allow known operational I/O
        if rel in allowed_io:
            continue
        lines = _read_lines(py_file)
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if open_pattern.search(stripped) or path_write.search(stripped):
                violations.append(f"{rel}:{i}: {stripped[:80]}")
                break
    return (len(violations) == 0, violations)


def check_logger_names() -> tuple[bool, list[str]]:
    """Check 3: all logger names use lowercase 'writesync'."""
    violations = []
    # Match getLogger calls: getLogger("WriteSync...") or getLogger('WriteSync...')
    logger_pattern = re.compile(r'getLogger\s*\(\s*["\']([wW]rite[Ss]ync[^"\')\s]*)')
    excluded = {"arch_lint.py"}

    for py_file in _walk_py_files(SRC):
        if py_file.name in excluded:
            continue
        lines = _read_lines(py_file)
        for i, line in enumerate(lines, 1):
            m = logger_pattern.search(line)
            if m:
                name = m.group(1)
                if name != "writesync":
                    rel = str(py_file.relative_to(ROOT)).replace("\\", "/")
                    violations.append(f"{rel}:{i}: getLogger('{name}') should be getLogger('writesync')")
    return (len(violations) == 0, violations)


def check_agent_registry() -> tuple[bool, list[str]]:
    """Check 4: agents in adapters.AGENT_MAP must also be in AGENT_REGISTRY."""
    violations = []

    # Parse adapters.py to find AGENT_MAP keys
    adapters_path = SRC / "orchestrator" / "adapters.py"
    if not adapters_path.exists():
        return (False, [f"Missing: {adapters_path.relative_to(ROOT)}"])

    adapters_text = adapters_path.read_text(encoding="utf-8")
    tree = ast.parse(adapters_text)
    agent_map_keys = []
    for node in ast.walk(tree):
        # Handle both Assign (x = ...) and AnnAssign (x: Type = ...)
        target_name = None
        node_value = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_name = target.id
                    node_value = node.value
                    break
        elif isinstance(node, ast.AnnAssign) and node.value:
            if isinstance(node.target, ast.Name):
                target_name = node.target.id
                node_value = node.value
        if target_name == "AGENT_MAP" and node_value and isinstance(node_value, ast.Dict):
            for key_node in node_value.keys:
                if isinstance(key_node, ast.Constant):
                    agent_map_keys.append(key_node.value)

    # Parse agent_registry.py to find AGENT_REGISTRY keys
    registry_path = SRC / "orchestrator" / "agent_registry.py"
    if not registry_path.exists():
        return (False, [f"Missing: {registry_path.relative_to(ROOT)}"])

    registry_text = registry_path.read_text(encoding="utf-8")
    reg_tree = ast.parse(registry_text)
    registry_keys = []
    for node in ast.walk(reg_tree):
        target_name = None
        node_value = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_name = target.id
                    node_value = node.value
                    break
        elif isinstance(node, ast.AnnAssign) and node.value:
            if isinstance(node.target, ast.Name):
                target_name = node.target.id
                node_value = node.value
        if target_name == "AGENT_REGISTRY" and node_value and isinstance(node_value, ast.Dict):
            for key_node in node_value.keys:
                if isinstance(key_node, ast.Constant):
                    registry_keys.append(key_node.value)

    # Cross-check
    for key in agent_map_keys:
        if key not in registry_keys:
            violations.append(f'Agent "{key}" missing from AGENT_REGISTRY')
    for key in registry_keys:
        if key not in agent_map_keys:
            violations.append(f'Agent "{key}" in AGENT_REGISTRY but not in AGENT_MAP')

    return (len(violations) == 0, violations)


def check_state_dataclass() -> tuple[bool, list[str]]:
    """Check 5: WriteSyncState uses @dataclass decorator."""
    violations = []
    state_path = SRC / "state" / "state_types.py"
    if not state_path.exists():
        return (False, [f"Missing: {state_path.relative_to(ROOT)}"])

    text = state_path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    found_write_sync = False
    has_dataclass = False
    # Track class definitions and their decorators
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "WriteSyncState":
            found_write_sync = True
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "dataclass":
                    has_dataclass = True
                elif isinstance(dec, ast.Call):
                    if isinstance(dec.func, ast.Name) and dec.func.id == "dataclass":
                        has_dataclass = True
                    elif isinstance(dec.func, ast.Attribute) and dec.func.attr == "dataclass":
                        has_dataclass = True

    if not found_write_sync:
        violations.append("WriteSyncState class not found in state_types.py")
    elif not has_dataclass:
        violations.append("WriteSyncState is missing @dataclass decorator")

    return (len(violations) == 0, violations)


# ── main ───────────────────────────────────────────────────────────────────

CHECKS = [
    ("Prompt isolation", check_hardcoded_prompts),
    ("File I/O isolation", check_file_io),
    ("Logger naming", check_logger_names),
    ("Agent registry sync", check_agent_registry),
    ("State @dataclass", check_state_dataclass),
]


def main():
    total = len(CHECKS)
    passed = 0
    failures: list[str] = []

    for name, check_fn in CHECKS:
        ok, msgs = check_fn()
        if ok:
            passed += 1
            print(f"PASS: {name}")
        else:
            print(f"FAIL: {name}")
            for msg in msgs:
                print(f"  → {msg}")
                failures.append(f"[{name}] {msg}")

    print()
    if passed == total:
        print(f"OK: {passed}/{total} checks passed")
        sys.exit(0)
    else:
        print(f"FAIL: {passed}/{total} checks passed, {total - passed} failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
