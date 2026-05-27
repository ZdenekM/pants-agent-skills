#!/usr/bin/env python3
"""Tracked-file-safe Pants repository probe.

The script discovers the nearest Pants build root and prints a small JSON
summary for agents. It does not edit tracked project files; Pants commands run
by default may still create local cache or daemon state.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback path.
    tomllib = None  # type: ignore[assignment]


CONFIG_CANDIDATES = ("pants.toml", "pants.ci.toml", ".pants.rc", ".pants.bootstrap")


def find_buildroot(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "pants.toml").is_file():
            return candidate
    return None


def load_toml(path: Path, warnings: list[str]) -> dict[str, Any]:
    if tomllib is None:
        warnings.append("Python tomllib is unavailable; pants.toml was not parsed.")
        return {}
    try:
        with path.open("rb") as handle:
            parsed = tomllib.load(handle)
    except Exception as exc:  # noqa: BLE001 - return a warning, not a traceback.
        warnings.append(f"Could not parse {path.name}: {exc}")
        return {}
    if not isinstance(parsed, dict):
        warnings.append(f"{path.name} did not parse as a TOML table.")
        return {}
    return parsed


def _list_option(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        items: list[str] = []
        for key in ("add", "append"):
            items.extend(_list_option(value.get(key)))
        return items
    return []


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(item, str):
            result[str(key)] = item
    return result


def extract_config(config: dict[str, Any]) -> dict[str, Any]:
    global_scope = config.get("GLOBAL", {})
    if not isinstance(global_scope, dict):
        global_scope = {}
    source_scope = config.get("source", {})
    if not isinstance(source_scope, dict):
        source_scope = {}
    python_scope = config.get("python", {})
    if not isinstance(python_scope, dict):
        python_scope = {}

    backends = _list_option(global_scope.get("backend_packages"))
    root_patterns = _list_option(source_scope.get("root_patterns"))
    marker_filenames = _list_option(source_scope.get("marker_filenames"))

    resolves = _string_map(python_scope.get("resolves"))
    python_info = {
        "enable_resolves": python_scope.get("enable_resolves"),
        "default_resolve": python_scope.get("default_resolve"),
        "resolves": resolves,
    }

    return {
        "pants_version_config": global_scope.get("pants_version"),
        "backends": backends,
        "source_root_patterns": root_patterns,
        "source_marker_filenames": marker_filenames,
        "python": python_info,
    }


def local_runner_candidates(buildroot: Path) -> list[Path]:
    names = ["pants"]
    if os.name == "nt":
        names.extend(["pants.bat", "pants.cmd", "pants.exe"])
    return [buildroot / name for name in names]


def choose_runner(buildroot: Path, warn_if_unavailable: bool = True) -> tuple[str, list[str]]:
    warnings: list[str] = []
    non_executable_candidates: list[str] = []
    for local_runner in local_runner_candidates(buildroot):
        if not local_runner.is_file():
            continue
        if os.name == "nt" or os.access(local_runner, os.X_OK):
            return f"./{local_runner.name}", warnings
        non_executable_candidates.append(local_runner.name)
    if non_executable_candidates and warn_if_unavailable:
        warnings.append(
            "Local Pants runner files exist but are not executable; using pants from PATH: "
            + ", ".join(non_executable_candidates)
        )
    if warn_if_unavailable and shutil.which("pants") is None:
        warnings.append("No executable ./pants wrapper and no pants executable found on PATH.")
    return "pants", warnings


def run_pants(
    buildroot: Path,
    runner: str,
    args: list[str],
    timeout: float,
) -> tuple[str | None, str | None]:
    cmd = [str(buildroot / runner[2:])] if runner.startswith("./") else [runner]
    cmd.extend(args)
    try:
        completed = subprocess.run(
            cmd,
            cwd=buildroot,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None, f"Could not run {' '.join(cmd)}: executable not found."
    except subprocess.TimeoutExpired:
        return None, f"Timed out running {' '.join(cmd)} after {timeout:g}s."
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout).strip().splitlines()
        suffix = f": {details[-1]}" if details else ""
        return None, f"{' '.join(cmd)} exited {completed.returncode}{suffix}"
    return completed.stdout.strip(), None


def probe(cwd: Path, timeout: float, files_only: bool) -> tuple[dict[str, Any], int]:
    warnings: list[str] = []
    buildroot = find_buildroot(cwd)
    if buildroot is None:
        return (
            {
                "cwd": str(cwd.resolve()),
                "buildroot": None,
                "runner": None,
                "pants_version": None,
                "config_files": [],
                "backends": [],
                "source_roots": [],
                "source_root_patterns": [],
                "source_marker_filenames": [],
                "python": {
                    "enable_resolves": None,
                    "default_resolve": None,
                    "resolves": {},
                },
                "warnings": ["No pants.toml found in current directory or parents."],
            },
            2,
        )

    config_files = [name for name in CONFIG_CANDIDATES if (buildroot / name).exists()]
    config = load_toml(buildroot / "pants.toml", warnings)
    extracted = extract_config(config)
    runner, runner_warnings = choose_runner(buildroot, warn_if_unavailable=not files_only)
    warnings.extend(runner_warnings)

    pants_version = None
    roots_output = None
    if not files_only:
        pants_version, warning = run_pants(buildroot, runner, ["--version"], timeout)
        if warning:
            warnings.append(warning)
        roots_output, warning = run_pants(buildroot, runner, ["roots"], timeout)
        if warning:
            warnings.append(warning)

    source_roots = []
    if roots_output:
        source_roots = [line.strip() for line in roots_output.splitlines() if line.strip()]
    if not source_roots:
        source_roots = extracted["source_root_patterns"]

    result = {
        "cwd": str(cwd.resolve()),
        "buildroot": str(buildroot),
        "runner": runner,
        "pants_version": pants_version or extracted["pants_version_config"],
        "config_files": config_files,
        "backends": extracted["backends"],
        "source_roots": source_roots,
        "source_root_patterns": extracted["source_root_patterns"],
        "source_marker_filenames": extracted["source_marker_filenames"],
        "python": extracted["python"],
        "warnings": warnings,
    }
    return result, 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tracked-file-safe Pants repository probe.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Directory to probe from.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Timeout for each Pants command in seconds.")
    parser.add_argument(
        "--files-only",
        action="store_true",
        help="Only parse files; do not run pants --version or pants roots.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    result, exit_code = probe(args.cwd, args.timeout, args.files_only)
    indent = 2 if args.pretty else None
    print(json.dumps(result, indent=indent, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
