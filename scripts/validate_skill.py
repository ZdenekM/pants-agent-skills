#!/usr/bin/env python3
"""Validate the Pants skill repository structure."""

from __future__ import annotations

import ast
import py_compile
import re
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "pants"
SKILL_MD = SKILL_DIR / "SKILL.md"
REPO_TEXT_ROOTS = (
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs",
    REPO_ROOT / "scripts",
    REPO_ROOT / "skills",
    REPO_ROOT / "tests",
)
REQUIRED_DESCRIPTION_GROUPS = {
    "pants identity": ("Pants", "Pantsbuild", "pants.toml", "BUILD"),
    "graph workflow": ("source roots", "dependency inference", "hermetic sandboxes", "Pants goals"),
    "backend breadth": ("Docker", "shell", "protobuf", "codegen"),
    "extension surface": ("plugins", "macros"),
    "parallel work": ("parallel", "workspace", "build roots"),
}


class ValidationError(Exception):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if not match:
        fail("SKILL.md must start with YAML frontmatter.")
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            fail(f"Invalid frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def validate_skill_md() -> None:
    if not SKILL_MD.is_file():
        fail(f"Missing {SKILL_MD}")
    text = SKILL_MD.read_text(encoding="utf-8")
    if "TODO" in text:
        fail("SKILL.md still contains TODO text.")

    frontmatter = parse_frontmatter(text)
    if set(frontmatter) != {"name", "description"}:
        fail("SKILL.md frontmatter must contain only name and description.")
    if frontmatter["name"] != SKILL_DIR.name:
        fail("Skill name must match the skill directory name.")

    description = frontmatter["description"]
    lower_description = description.lower()
    if len(description) > 420:
        fail("Skill description should stay concise enough for trigger metadata.")
    for group, terms in REQUIRED_DESCRIPTION_GROUPS.items():
        missing = [term for term in terms if term.lower() not in lower_description]
        if missing:
            fail(f"Skill description is missing {group} trigger terms: {missing}")

    for ref in sorted(set(re.findall(r"references/([A-Za-z0-9_.-]+\.md)", text))):
        path = SKILL_DIR / "references" / ref
        if not path.is_file():
            fail(f"SKILL.md references missing file: {path}")

    runtime_specific = ("Codex", "OpenAI", "CODEX_HOME", ".codex")
    for marker in runtime_specific:
        if marker in text:
            fail(f"SKILL.md should stay runtime-neutral; found {marker!r}.")


def validate_no_private_paths() -> None:
    forbidden = (
        "/home/" + "zdenekm",
        "~/" + "code/",
        "BEGIN PRIVATE " + "KEY",
        "api" + "_key",
        "password" + " =",
    )
    files: list[Path] = []
    for root in REPO_TEXT_ROOTS:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(path for path in root.rglob("*") if path.is_file())

    for path in sorted(files):
        if path.suffix == ".pyc" or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                fail(f"Forbidden private marker {marker!r} in {path}")


def validate_probe_script() -> None:
    probe = SKILL_DIR / "scripts" / "pants_repo_probe.py"
    if not probe.is_file():
        fail("Missing pants_repo_probe.py")
    source = probe.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(probe))
    forbidden_attrs = {"rmtree", "unlink", "remove", "replace", "rename", "write_text", "write_bytes"}

    def is_mutating_mode(node: ast.AST | None) -> bool:
        if isinstance(node, ast.Constant):
            mode = str(node.value)
            return any(flag in mode for flag in ("w", "a", "+", "x"))
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            fail(f"Probe script uses potentially mutating API: {node.attr}")
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            positional_mode = node.args[1] if len(node.args) >= 2 else None
            keyword_mode = next((kw.value for kw in node.keywords if kw.arg == "mode"), None)
            if is_mutating_mode(positional_mode) or is_mutating_mode(keyword_mode):
                fail("Probe script opens a file in a mutating mode.")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            positional_mode = node.args[0] if node.args else None
            keyword_mode = next((kw.value for kw in node.keywords if kw.arg == "mode"), None)
            if is_mutating_mode(positional_mode) or is_mutating_mode(keyword_mode):
                fail("Probe script opens a file in a mutating mode.")
    py_compile.compile(str(probe), doraise=True)


def validate_repo_scripts() -> None:
    for script in (REPO_ROOT / "scripts" / "install_skill.py", REPO_ROOT / "scripts" / "validate_skill.py"):
        if not script.is_file():
            fail(f"Missing repo script: {script}")
        py_compile.compile(str(script), doraise=True)

    install_text = (REPO_ROOT / "scripts" / "install_skill.py").read_text(encoding="utf-8")
    if "--force" not in install_text or "--backup" not in install_text:
        fail("Installer must expose --force and --backup overwrite controls.")
    if "--runtime" not in install_text or "--target-root" not in install_text:
        fail("Installer must support runtime profiles and explicit target roots.")


def validate_references() -> None:
    expected = {
        "pants-core-workflow.md",
        "pants-docker-shell.md",
        "pants-python.md",
        "pants-troubleshooting.md",
        "parallel-pants-workspaces.md",
        "sources.md",
    }
    actual = {path.name for path in (SKILL_DIR / "references").glob("*.md")}
    missing = expected - actual
    if missing:
        fail(f"Missing reference files: {sorted(missing)}")


def main() -> int:
    checks = [
        validate_skill_md,
        validate_references,
        validate_no_private_paths,
        validate_probe_script,
        validate_repo_scripts,
    ]
    for check in checks:
        check()
        print(f"OK {check.__name__}")
    print("Skill validation passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(1)
