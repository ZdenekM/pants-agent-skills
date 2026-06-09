from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_HELPER = REPO_ROOT / "skills" / "pants" / "scripts" / "pants_cache_maintenance.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "minimal-python-pants"


def configure_relative_caches(buildroot: Path) -> tuple[Path, Path]:
    pants_toml = buildroot / "pants.toml"
    text = pants_toml.read_text(encoding="utf-8")
    text = text.replace(
        "[source]",
        'named_caches_dir = "cache/named"\nlocal_store_dir = "cache/store"\n\n[source]',
    )
    pants_toml.write_text(text, encoding="utf-8")
    return buildroot / "cache" / "named", buildroot / "cache" / "store"


def run_helper(buildroot: Path, *args: str) -> dict[str, object]:
    home = buildroot.parent / "home"
    home.mkdir(exist_ok=True)
    completed = subprocess.run(
        [sys.executable, str(CACHE_HELPER), "--cwd", str(buildroot), "--home", str(home), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return json.loads(completed.stdout)


def cache_by_name(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    caches = payload["caches"]
    assert isinstance(caches, list)
    return {str(cache["name"]): cache for cache in caches}


class PantsCacheMaintenanceTest(unittest.TestCase):
    def test_default_report_does_not_delete_cache_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)
            named_cache.mkdir(parents=True)
            (named_cache / "cache.bin").write_bytes(b"x" * 32)

            payload = run_helper(buildroot)
            caches = cache_by_name(payload)

            self.assertTrue(named_cache.exists())
            self.assertEqual(caches["named_caches"]["path"], str(named_cache))
            self.assertEqual(caches["named_caches"]["action"], "report")
            self.assertGreater(caches["named_caches"]["size_bytes"], 0)
            self.assertFalse(payload["apply"])

    def test_limit_without_apply_reports_would_delete_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)
            named_cache.mkdir(parents=True)
            (named_cache / "cache.bin").write_bytes(b"x")

            payload = run_helper(buildroot, "--limit", "named_caches=0")
            caches = cache_by_name(payload)

            self.assertTrue(named_cache.exists())
            self.assertEqual(caches["named_caches"]["action"], "would_delete")
            self.assertTrue(caches["named_caches"]["exists"])

    def test_relative_cache_options_are_resolved_from_buildroot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, local_store = configure_relative_caches(buildroot)

            payload = run_helper(buildroot / "src" / "example")
            caches = cache_by_name(payload)

            self.assertEqual(caches["named_caches"]["path"], str(named_cache))
            self.assertEqual(caches["local_store"]["path"], str(local_store))

    def test_apply_deletes_only_cache_directories_over_explicit_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, local_store = configure_relative_caches(buildroot)
            named_cache.mkdir(parents=True)
            local_store.mkdir(parents=True)
            (named_cache / "cache.bin").write_bytes(b"x")
            (local_store / "store.bin").write_bytes(b"x")

            payload = run_helper(
                buildroot,
                "--limit",
                "named_caches=0",
                "--limit",
                "local_store=1024",
                "--apply",
            )
            caches = cache_by_name(payload)

            self.assertFalse(named_cache.exists())
            self.assertTrue(local_store.exists())
            self.assertEqual(caches["named_caches"]["action"], "deleted")
            self.assertTrue(caches["named_caches"]["exists_before"])
            self.assertFalse(caches["named_caches"]["exists"])
            self.assertEqual(caches["local_store"]["action"], "report")


if __name__ == "__main__":
    unittest.main()
