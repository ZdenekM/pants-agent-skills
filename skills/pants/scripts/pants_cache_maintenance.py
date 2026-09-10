#!/usr/bin/env python3
"""Report and optionally trim Pants cache directories.

The default mode is read-only. Deletion only happens with --apply and an
explicit --limit for the cache category that is over the limit.

Cache locations are resolved the way Pants resolves them: `pants.toml`, then
any `pantsrc_files` that exist, then `PANTS_*` environment variables. A repo's
`pants.toml` is therefore not authoritative on its own -- a machine-level rc
file can redirect the cache elsewhere and leave the directory named in
`pants.toml` behind as dead weight. Those shadowed directories are reported
separately so they are not mistaken for the live cache.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

from pants_repo_probe import _list_option, find_buildroot, load_toml


CACHE_NAMES = ("launcher", "named_caches", "local_store")
BYTES_PER_MB = 1024 * 1024

# Pants reads these after pants.toml; later files win. Mirrors the default
# value of the `pantsrc_files` option.
DEFAULT_PANTSRC_FILES = ("/etc/pantsrc", "~/.pants.rc", ".pants.rc")

# Environment overrides take precedence over every config file.
ENV_OVERRIDES = {
    "named_caches": "PANTS_NAMED_CACHES_DIR",
    "local_store": "PANTS_LOCAL_STORE_DIR",
}

CONFIG_KEYS = {
    "named_caches": "named_caches_dir",
    "local_store": "local_store_dir",
}


def platform_cache_dir(home: Path) -> Path:
    """The OS cache directory, resolved the way Pants' engine resolves it.

    Pants has no Python-side reference to XDG_CACHE_HOME, but its native engine
    honors it on Linux -- verified against a live Pants: with XDG_CACHE_HOME
    set, `help-advanced global` reports the defaults under that directory.
    """
    if sys.platform == "darwin":
        return home / "Library" / "Caches"
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        return Path(local_app_data) if local_app_data else home / "AppData" / "Local"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg and xdg.strip() and os.path.isabs(xdg):
        return Path(xdg)
    return home / ".cache"


def default_launcher_cache(home: Path) -> Path:
    # The scie launcher stores its bootstraps under SCIE_BASE when set.
    scie_base = os.environ.get("SCIE_BASE")
    if scie_base and scie_base.strip():
        return Path(scie_base)
    return platform_cache_dir(home) / "nce"


def user_pex_roots(home: Path) -> list[Path]:
    """PEX_ROOT locations pex uses outside any Pants-managed named cache.

    Current pex defaults to the platform cache dir; older versions used
    ``~/.pex``. Both can hold tens of gigabytes and neither is bounded by any
    Pants option, so both are reported.
    """
    primary = platform_cache_dir(home) / "pex"

    env_root = os.environ.get("PEX_ROOT")
    roots: list[Path] = []
    if env_root and env_root.strip():
        # PEX_ROOT is routinely exported as "~/.cache/pex"; without expansion
        # that is a relative path that never exists and the user's real pex
        # root drops out of the report entirely.
        roots.append(expand_pants_path(env_root, primary, home, home))
    roots.extend([primary, home / ".pex"])

    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = _real(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def expand_pants_path(value: Any, default: Path, buildroot: Path, home: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        return default

    # Expand environment variables on the raw value, before interpolation, so a
    # "$" inside the buildroot or home path is never treated as a variable.
    expanded = os.path.expandvars(value)
    expanded = expanded.replace("%(homedir)s", str(home)).replace("%(buildroot)s", str(buildroot))
    expanded = re.sub(
        r"%\(env\.([A-Za-z_][A-Za-z0-9_]*)\)s",
        lambda match: os.environ.get(match.group(1), ""),
        expanded,
    )

    # Resolve "~" against the home passed in, not the process environment, so a
    # caller can point the whole resolution at a different home directory.
    # "~user" is deliberately NOT expanded: consulting the system password
    # database would escape that home.
    if expanded == "~":
        expanded = str(home)
    elif expanded.startswith("~/") or expanded.startswith("~" + os.sep):
        remainder = expanded[2:].lstrip("/").lstrip(os.sep)
        expanded = str(home / remainder) if remainder else str(home)

    path = Path(expanded)
    if path.is_absolute():
        return path
    return buildroot / path


def has_unresolved_interpolation(path: Path) -> bool:
    """True when a `%(...)s` placeholder survived expansion.

    Pants supports `[DEFAULT]` substitutions this helper does not implement.
    Treating such a value as a real directory would invent a path and, worse,
    make the genuinely live cache look abandoned.
    """
    return "%(" in str(path)


def _within(inner: str, outer: str) -> bool:
    return inner == outer or inner.startswith(outer.rstrip(os.sep) + os.sep)


def _real(path: Path) -> str:
    """Normalized identity of a path, for comparing two spellings of one dir.

    Home directories and build roots are commonly symlinks, so raw Path
    equality reports the live cache as a stale duplicate of itself.
    """
    return os.path.realpath(str(path))


def _global_scope(config: dict[str, Any]) -> dict[str, Any]:
    scope = config.get("GLOBAL", {})
    return scope if isinstance(scope, dict) else {}


def _parse_env_list(raw: str, current: list[str]) -> list[str]:
    """Parse a Pants list option supplied through the environment.

    A leading "+" is Pants' append syntax: it extends the existing value rather
    than replacing it. Reading it as a replacement drops rc files that redirect
    the cache, which would point deletion at the wrong directory.
    """
    text = raw.strip()
    append = text.startswith("+")
    if append:
        text = text[1:].strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    items = [item.strip().strip("'\"") for item in re.split(r"[,\n]+", text)]
    parsed = [item for item in items if item]
    return current + parsed if append else parsed


def _apply_list_ops(raw: Any, current: list[str]) -> list[str]:
    """Resolve a TOML list option that may use Pants' add/remove dict form."""
    if isinstance(raw, dict):
        result = list(current)
        result.extend(_list_option(raw))
        for item in _list_option(raw.get("remove")):
            while item in result:
                result.remove(item)
        return result
    return _list_option(raw)


def config_layers(
    buildroot: Path, home: Path, warnings: list[str]
) -> tuple[list[tuple[str, dict[str, Any]]], bool]:
    """Config sources in Pants precedence order, lowest first.

    The second element is False when a config file could not be read or parsed.
    Resolution then silently falls back to defaults, so deletion must be
    refused rather than aimed at a directory we only guessed at.
    """
    config_problems: list[str] = []

    def read(path: Path) -> dict[str, Any]:
        local: list[str] = []
        parsed = load_toml(path, local)
        warnings.extend(local)
        config_problems.extend(local)
        return _global_scope(parsed)

    default_config = buildroot / "pants.toml"
    env_config = os.environ.get("PANTS_CONFIG_FILES")
    if env_config is not None and env_config.strip():
        config_files = _parse_env_list(env_config, ["pants.toml"])
    else:
        config_files = ["pants.toml"]

    layers: list[tuple[str, dict[str, Any]]] = []
    base: dict[str, Any] = {}
    for raw_config in config_files:
        config_path = expand_pants_path(raw_config, default_config, buildroot, home)
        if not config_path.is_file():
            continue
        scope = read(config_path)
        layers.append((str(config_path), scope))
        base = {**base, **scope}
    if not layers:
        layers = [(str(default_config), {})]

    env_pantsrc = os.environ.get("PANTS_PANTSRC")
    if env_pantsrc is not None and env_pantsrc.strip():
        enabled = env_pantsrc.strip().lower() not in ("false", "0", "no", "off")
    else:
        enabled = base.get("pantsrc", True) is not False
    if not enabled:
        return layers, not config_problems

    if "pantsrc_files" in base:
        # An explicit empty list disables rc files; `.add`/`.remove` adjust the
        # defaults rather than replacing them.
        rc_files = _apply_list_ops(base["pantsrc_files"], list(DEFAULT_PANTSRC_FILES))
    else:
        rc_files = list(DEFAULT_PANTSRC_FILES)

    env_files = os.environ.get("PANTS_PANTSRC_FILES")
    if env_files is not None and env_files.strip():
        rc_files = _parse_env_list(env_files, rc_files)

    for raw in rc_files:
        rc_path = expand_pants_path(raw, buildroot, buildroot, home)
        if rc_path.is_file():
            layers.append((str(rc_path), read(rc_path)))
    return layers, not config_problems


def resolve_cache_option(
    name: str,
    layers: list[tuple[str, dict[str, Any]]],
    default: Path,
    buildroot: Path,
    home: Path,
) -> tuple[Path, str, list[tuple[Path, str]]]:
    """Return (effective path, source label, every candidate location).

    Candidates include the built-in default and each configured value, in
    precedence order. Any candidate that is not the effective one is a place a
    cache may have been left behind -- including the built-in default, which a
    repo abandons the moment it sets the option for the first time.
    """
    candidates: list[tuple[Path, str]] = [(default, "default")]
    key = CONFIG_KEYS.get(name)
    if key is None:
        return default, "default", candidates

    effective = default
    source = "default"
    for label, scope in layers:
        value = scope.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        resolved = expand_pants_path(value, default, buildroot, home)
        candidates.append((resolved, label))
        effective = resolved
        source = label

    env_name = ENV_OVERRIDES.get(name)
    env_value = os.environ.get(env_name) if env_name else None
    if env_value and env_value.strip():
        resolved = expand_pants_path(env_value, default, buildroot, home)
        candidates.append((resolved, f"env:{env_name}"))
        effective = resolved
        source = f"env:{env_name}"

    return effective, source, candidates


def directory_stats(path: Path, warnings: list[str]) -> dict[str, Any]:
    """Sum file sizes, counting each inode once.

    PEX caches hardlink installed wheels into every venv that uses them, so
    summing file sizes without deduplicating inodes overstates a pex root
    several-fold and makes size-based limits fire on bytes that do not exist.

    This is not identical to `du`: it sums `st_size` rather than allocated
    blocks and ignores directory inodes, so sparse files read high and the
    total will not match `du -s` exactly.
    """
    empty = {"size_bytes": 0, "apparent_size_bytes": 0, "file_count": 0, "newest_mtime": None}
    if not path.exists():
        return empty
    # is_dir() follows symlinks on purpose: relocating a cache to a bigger disk
    # and leaving a symlink behind is normal, and such a cache must still be
    # measured. Deleting through the symlink stays refused.
    if not path.is_dir():
        warnings.append(f"{path} is not a directory; skipping size traversal.")
        return empty

    total = 0
    apparent = 0
    file_count = 0
    newest: float | None = None
    seen_inodes: set[tuple[int, int]] = set()

    for root, _, files in os.walk(
        path, onerror=lambda exc: warnings.append(f"Could not traverse {exc.filename}: {exc}")
    ):
        for filename in files:
            item = Path(root) / filename
            try:
                stat_result = item.lstat()
            except OSError as exc:
                warnings.append(f"Could not stat {item}: {exc}")
                continue
            file_count += 1
            apparent += stat_result.st_size
            if newest is None or stat_result.st_mtime > newest:
                newest = stat_result.st_mtime
            if stat_result.st_nlink > 1:
                key = (stat_result.st_dev, stat_result.st_ino)
                if key in seen_inodes:
                    continue
                seen_inodes.add(key)
            total += stat_result.st_size

    return {
        "size_bytes": total,
        "apparent_size_bytes": apparent,
        "file_count": file_count,
        "newest_mtime": newest,
    }


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


def _size_fields(stats: dict[str, Any]) -> dict[str, Any]:
    size_bytes = int(stats["size_bytes"])
    return {
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / BYTES_PER_MB, 3),
        "apparent_size_bytes": int(stats["apparent_size_bytes"]),
        "file_count": int(stats["file_count"]),
        "newest_mtime": stats["newest_mtime"],
    }


def inspect_cache(
    name: str,
    path: Path,
    source: str,
    limit_mb: int | None,
    apply: bool,
    warnings: list[str],
) -> dict[str, Any]:
    exists_before = path.exists()
    stats = directory_stats(path, warnings)
    size_bytes = int(stats["size_bytes"])
    over_limit = False if limit_mb is None else size_bytes > limit_mb * BYTES_PER_MB

    action = "report"
    if limit_mb is not None and over_limit:
        action = remove_directory_via_nuke(path, warnings) if apply else "would_delete"
    elif not exists_before:
        action = "missing"

    return {
        "name": name,
        "path": str(path),
        "source": source,
        "exists": path.exists(),
        "exists_before": exists_before,
        "limit_mb": limit_mb,
        "over_limit": over_limit,
        "action": action,
        **_size_fields(stats),
    }


def inspect_reported_dir(name: str, path: Path, kind: str, warnings: list[str]) -> dict[str, Any]:
    """Report-only entry. Never deleted by --apply."""
    stats = directory_stats(path, warnings)
    return {
        "name": name,
        "path": str(path),
        "kind": kind,
        "exists": path.exists(),
        **_size_fields(stats),
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
                "shadowed_caches": [],
                "pex_roots": [],
                "warnings": ["No pants.toml found in current directory or parents."],
            },
            2,
        )

    if apply and not limits:
        warnings.append("--apply was provided without --limit; no cache directory will be deleted.")

    layers, config_trusted = config_layers(buildroot, home, warnings)
    pants_cache_root = platform_cache_dir(home) / "pants"
    defaults = {
        "launcher": default_launcher_cache(home),
        "named_caches": pants_cache_root / "named_caches",
        "local_store": pants_cache_root / "lmdb_store",
    }

    # Resolve every category before deleting anything, so the report describes
    # the state the caller decided against rather than the state after.
    resolved: dict[str, tuple[Path, str, list[tuple[Path, str]]]] = {
        name: resolve_cache_option(name, layers, defaults[name], buildroot, home) for name in CACHE_NAMES
    }
    effective_real = {_real(path) for path, _, _ in resolved.values()}

    # Refuse deletion whenever the resolved location is not trustworthy: an
    # unreadable config silently falls back to defaults, and an unsupported
    # `%(...)s` substitution yields a path that does not exist. Deleting on
    # either basis targets a directory we never actually resolved.
    unresolved = sorted(
        {str(path) for path, _, _ in resolved.values() if has_unresolved_interpolation(path)}
    )
    if unresolved:
        warnings.append(
            "Unsupported config interpolation left placeholders in: "
            + ", ".join(unresolved)
            + ". Resolve with `pants --no-pantsd help-advanced global`."
        )
    if apply and (not config_trusted or unresolved):
        apply = False
        warnings.append(
            "--apply was disabled: cache locations could not be resolved with confidence."
        )

    named_caches_path = resolved["named_caches"][0]
    pex_root_paths: list[tuple[str, Path, str]] = [
        ("named_caches_pex_root", named_caches_path / "pex_root", "pants_managed")
    ]
    pex_root_paths.extend(
        (f"user_pex_root_{index}", root, "user_managed") for index, root in enumerate(user_pex_roots(home))
    )
    pex_roots = [
        inspect_reported_dir(name, path, kind, warnings)
        for name, path, kind in pex_root_paths
        if path.exists()
    ]
    # A pex root nested inside a cache category is removed along with it. Say so
    # rather than letting it vanish from the report.
    named_real = _real(named_caches_path)
    for entry in pex_roots:
        nested = _real(Path(str(entry["path"]))).startswith(named_real + os.sep)
        entry["inside_named_caches"] = nested
        if nested and limits.get("named_caches") is not None:
            entry["note"] = "deleted with named_caches when that limit is exceeded"

    shadowed_caches: list[dict[str, Any]] = []
    seen_shadowed: set[str] = set()
    for name in CACHE_NAMES:
        effective, source, candidates = resolved[name]
        for candidate, label in candidates:
            key = _real(candidate)
            if key in seen_shadowed or not candidate.exists():
                continue
            if has_unresolved_interpolation(candidate):
                continue
            # Never call a directory unused when it is, or contains, a live
            # cache: an ancestor of the effective path holds it, and deleting
            # it on this report's word would take the live cache with it.
            if any(_within(key, live) or _within(live, key) for live in effective_real):
                continue
            seen_shadowed.add(key)
            entry = inspect_reported_dir(name, candidate, "shadowed_by_config", warnings)
            entry["declared_by"] = label
            entry["effective_path"] = str(effective)
            entry["effective_source"] = source
            shadowed_caches.append(entry)

    # Deletion happens last: everything above describes the pre-deletion state.
    caches = [
        inspect_cache(name, resolved[name][0], resolved[name][1], limits.get(name), apply, warnings)
        for name in CACHE_NAMES
    ]

    if shadowed_caches:
        warnings.append(
            "Cache directories exist at locations the effective config does not use. "
            "Pants neither reads nor writes them; verify with "
            "`pants --no-pantsd help-advanced global` before deleting them. "
            "When one is a repo-local .pants.d path, keep .pants.d/workdir and .pants.d/pids."
        )

    return (
        {
            "cwd": str(cwd.resolve()),
            "buildroot": str(buildroot),
            "apply": apply,
            "home": str(home),
            "config_layers": [label for label, _ in layers],
            "config_trusted": config_trusted,
            "caches": caches,
            "shadowed_caches": shadowed_caches,
            "pex_roots": pex_roots,
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
