#!/usr/bin/env python3
"""Install the Pants skill bundle into an agent runtime skill directory."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_DIR = REPO_ROOT / "skills" / "pants"


def target_root_for_runtime(runtime: str) -> Path:
    import os

    if runtime == "codex":
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return codex_home / "skills"
    if runtime != "generic":
        raise SystemExit(f"Unknown runtime profile: {runtime}")

    configured = os.environ.get("AGENT_SKILLS_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".agents" / "skills"


def copy_skill(source: Path, target: Path, dry_run: bool, force: bool, backup: bool) -> None:
    if not source.is_dir():
        raise SystemExit(f"Skill source does not exist: {source}")

    if target.exists():
        if backup:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = target.with_name(f"{target.name}.backup.{timestamp}")
            print(f"Backup existing skill: {target} -> {backup_path}")
            if not dry_run:
                target.rename(backup_path)
        elif force:
            print(f"Replace existing skill: {target}")
            if not dry_run:
                shutil.rmtree(target)
        else:
            raise SystemExit(
                f"Target already exists: {target}\n"
                "Use --backup to preserve it or --force to replace it."
            )

    print(f"Install skill: {source} -> {target}")
    if dry_run:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install the Pants Agent Skill.")
    parser.add_argument("--skill-dir", type=Path, default=DEFAULT_SKILL_DIR, help="Source skill directory.")
    parser.add_argument("--target-root", type=Path, help="Directory that contains installed skills.")
    parser.add_argument(
        "--runtime",
        choices=("generic", "codex"),
        default="generic",
        help=(
            "Runtime install profile. generic uses $AGENT_SKILLS_DIR or "
            "$HOME/.agents/skills; codex uses ${CODEX_HOME:-$HOME/.codex}/skills."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without copying files.")
    parser.add_argument("--force", action="store_true", help="Replace an existing installed skill.")
    parser.add_argument("--backup", action="store_true", help="Rename an existing installed skill before copying.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.force and args.backup:
        raise SystemExit("Use either --force or --backup, not both.")

    target_root = args.target_root.expanduser() if args.target_root else target_root_for_runtime(args.runtime)
    source = args.skill_dir.expanduser().resolve()
    target = target_root.expanduser() / source.name
    copy_skill(source, target, args.dry_run, args.force, args.backup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
