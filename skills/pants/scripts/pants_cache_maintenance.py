#!/usr/bin/env python3
"""Report and optionally trim Pants cache directories.

The default mode is read-only. Deletion only happens with --apply and an
explicit --limit for the cache category that is over the limit.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from pants_repo_probe import find_buildroot, load_toml


CACHE_NAMES = ("launcher", "named_caches", "local_store")
BYTES_PER_MB = 1024 * 1024


def default_launcher_cache(home: Path) -> Path:
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "nce"
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "nce"
        return home / "AppData" / "Local" / "nce"
    return home / ".cache" / "nce"


def expand_pants_path(value: Any, default: Path, buildroot: Path, home: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        return default

    expanded = value.replace("%(homedir)s", str(home)).replace("%(buildroot)s", str(buildroot))
    path = Path(os.path.expandvars(os.path.expanduser(expanded)))
    if path.is_absolute():
        return path
    return buildroot / path


def pants_cache_paths(buildroot: Path, config: dict[str, Any], home: Path) -> dict[str, Path]:
    global_scope = config.get("GLOBAL", {})
    if not isinstance(global_scope, dict):
        global_scope = {}

    pants_cache_root = home / ".cache" / "pants"
    return {
        "launcher": default_launcher_cache(home),
        "named_caches": expand_pants_path(
            global_scope.get("named_caches_dir"),
            pants_cache_root / "named_caches",
            buildroot,
            home,
        ),
        "local_store": expand_pants_path(
            global_scope.get("local_store_dir"),
            pants_cache_root / "lmdb_store",
            buildroot,
            home,
        ),
    }


def directory_size_bytes(path: Path, warnings: list[str]) -> int:
    if not path.exists():
        return 0
    if not path.is_dir() or path.is_symlink():
        warnings.append(f"{path} is not a directory; skipping size traversal.")
        return 0

    total = 0
    for root, _, files in os.walk(path, onerror=lambda exc: warnings.append(f"Could not traverse {exc.filename}: {exc}")):
        for filename in files:
            item = Path(root) / filename
            try:
                total += item.lstat().st_size
            except OSError as exc:
                warnings.append(f"Could not stat {item}: {exc}")
    return total


def remove_directory_via_nuke(path: Path, warnings: list[str]) -> str:
    if not path.exists():
        return "missing"
    if not path.is_dir() or path.is_symlink():
        warnings.append(f"{path} is not a directory; refusing to delete it.")
        return "skipped"

    try:
        nuke_root = Path(tempfile.mkdtemp(prefix=f"{path.name}.nuke.", dir=path.parent))
        path.rename(nuke_root / path.name)
        shutil.rmtree(nuke_root)
    except OSError as exc:
        warnings.append(f"Could not delete {path}: {exc}")
        return "error"
    return "deleted"


def parse_limits(raw_limits: list[str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    for raw_limit in raw_limits:
        if "=" not in raw_limit:
            raise ValueError(f"Invalid limit {raw_limit!r}; expected NAME=MB.")
        name, raw_mb = raw_limit.split("=", 1)
        if name not in CACHE_NAMES:
            raise ValueError(f"Unknown cache {name!r}; expected one of {', '.join(CACHE_NAMES)}.")
        if name in limits:
            raise ValueError(f"Duplicate limit for {name!r}.")
        try:
            limit_mb = int(raw_mb)
        except ValueError as exc:
            raise ValueError(f"Invalid MB value for {name!r}: {raw_mb!r}.") from exc
        if limit_mb < 0:
            raise ValueError(f"Limit for {name!r} must be non-negative.")
        limits[name] = limit_mb
    return limits


def inspect_cache(
    name: str,
    path: Path,
    limit_mb: int | None,
    apply: bool,
    warnings: list[str],
) -> dict[str, Any]:
    exists_before = path.exists()
    size_bytes = directory_size_bytes(path, warnings)
    over_limit = False if limit_mb is None else size_bytes > limit_mb * BYTES_PER_MB

    action = "report"
    if limit_mb is not None and over_limit:
        action = remove_directory_via_nuke(path, warnings) if apply else "would_delete"
    elif not exists_before:
        action = "missing"

    exists_after = path.exists()
    return {
        "name": name,
        "path": str(path),
        "exists": exists_after,
        "exists_before": exists_before,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / BYTES_PER_MB, 3),
        "limit_mb": limit_mb,
        "over_limit": over_limit,
        "action": action,
    }


def build_report(cwd: Path, home: Path, limits: dict[str, int], apply: bool) -> tuple[dict[str, Any], int]:
    warnings: list[str] = []
    home = home.expanduser().resolve()
    buildroot = find_buildroot(cwd)
    if buildroot is None:
        return (
            {
                "cwd": str(cwd.resolve()),
                "buildroot": None,
                "apply": apply,
                "home": str(home),
                "caches": [],
                "warnings": ["No pants.toml found in current directory or parents."],
            },
            2,
        )

    if apply and not limits:
        warnings.append("--apply was provided without --limit; no cache directory will be deleted.")

    config = load_toml(buildroot / "pants.toml", warnings)
    cache_paths = pants_cache_paths(buildroot, config, home)
    caches = [
        inspect_cache(name, cache_paths[name], limits.get(name), apply, warnings)
        for name in CACHE_NAMES
    ]

    return (
        {
            "cwd": str(cwd.resolve()),
            "buildroot": str(buildroot),
            "apply": apply,
            "home": str(home),
            "caches": caches,
            "warnings": warnings,
        },
        0,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report and optionally trim Pants cache directories.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Directory to inspect from.")
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="Home directory used to resolve default global Pants cache paths.",
    )
    parser.add_argument(
        "--limit",
        action="append",
        default=[],
        metavar="NAME=MB",
        help=f"Delete only when NAME exceeds MB. Names: {', '.join(CACHE_NAMES)}.",
    )
    parser.add_argument("--apply", action="store_true", help="Delete cache directories that exceed explicit limits.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args(argv)
    try:
        args.limits = parse_limits(args.limit)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result, exit_code = build_report(args.cwd, args.home, args.limits, args.apply)
    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
