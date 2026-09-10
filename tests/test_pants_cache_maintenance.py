from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_HELPER = REPO_ROOT / "skills" / "pants" / "scripts" / "pants_cache_maintenance.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "minimal-python-pants"


def configure_relative_caches(buildroot: Path, pantsrc_files: str = "[]") -> tuple[Path, Path]:
    """Point the fixture at repo-relative caches.

    `pantsrc_files` defaults to an empty list so the absolute default
    `/etc/pantsrc` is never read: a machine that happens to have one would
    otherwise redirect the cache under test to a real directory.
    """
    pants_toml = buildroot / "pants.toml"
    text = pants_toml.read_text(encoding="utf-8")
    text = text.replace(
        "[source]",
        'named_caches_dir = "cache/named"\n'
        'local_store_dir = "cache/store"\n'
        f"pantsrc_files = {pantsrc_files}\n\n"
        "[source]",
    )
    pants_toml.write_text(text, encoding="utf-8")
    return buildroot / "cache" / "named", buildroot / "cache" / "store"


def write_pantsrc(buildroot: Path, named_cache: Path, local_store: Path) -> Path:
    """Write an rc file into the isolated home used by run_helper."""
    home = buildroot.parent / "home"
    home.mkdir(exist_ok=True)
    rc_path = home / ".pants.rc"
    rc_path.write_text(
        "[GLOBAL]\n"
        f'named_caches_dir = "{named_cache.as_posix()}"\n'
        f'local_store_dir = "{local_store.as_posix()}"\n',
        encoding="utf-8",
    )
    return rc_path


def run_helper(buildroot: Path, *args: str, env: dict[str, str] | None = None) -> dict[str, object]:
    home = buildroot.parent / "home"
    home.mkdir(exist_ok=True)
    child_env = dict(os.environ)
    # Scrub every Pants/PEX variable. PANTS_NAMED_CACHES_DIR and
    # PANTS_LOCAL_STORE_DIR outrank both the config layers and the --home
    # sandbox, so a developer with one exported would have the destructive
    # --apply tests delete their real cache while still passing.
    for key in [key for key in child_env if key.startswith("PANTS_")]:
        del child_env[key]
    # These steer the default cache locations too, and would otherwise point
    # the helper at directories outside the temporary --home.
    for key in ("PEX_ROOT", "XDG_CACHE_HOME", "LOCALAPPDATA", "SCIE_BASE"):
        child_env.pop(key, None)
    child_env.update(env or {})
    completed = subprocess.run(
        [sys.executable, str(CACHE_HELPER), "--cwd", str(buildroot), "--home", str(home), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=child_env,
    )
    return json.loads(completed.stdout)


def cache_by_name(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    caches = payload["caches"]
    assert isinstance(caches, list)
    return {str(cache["name"]): cache for cache in caches}


def shadowed_paths(payload: dict[str, object]) -> set[str]:
    shadowed = payload["shadowed_caches"]
    assert isinstance(shadowed, list)
    return {str(item["path"]) for item in shadowed}


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


class PantsrcResolutionTest(unittest.TestCase):
    def test_pantsrc_overrides_pants_toml_and_old_location_is_reported_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            declared_named, _ = configure_relative_caches(buildroot, pantsrc_files='["~/.pants.rc"]')
            declared_named.mkdir(parents=True)
            (declared_named / "stale.bin").write_bytes(b"x" * 64)

            live_named = Path(tmp) / "live" / "named"
            live_store = Path(tmp) / "live" / "store"
            live_named.mkdir(parents=True)
            write_pantsrc(buildroot, live_named, live_store)

            payload = run_helper(buildroot)
            caches = cache_by_name(payload)

            self.assertEqual(caches["named_caches"]["path"], str(live_named))
            self.assertEqual(caches["local_store"]["path"], str(live_store))
            self.assertIn(str(declared_named), shadowed_paths(payload))
            self.assertTrue(declared_named.exists())

    def test_environment_variable_wins_over_every_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            configure_relative_caches(buildroot, pantsrc_files='["~/.pants.rc"]')
            write_pantsrc(buildroot, Path(tmp) / "rc" / "named", Path(tmp) / "rc" / "store")

            env_named = Path(tmp) / "fromenv" / "named"
            payload = run_helper(buildroot, env={"PANTS_NAMED_CACHES_DIR": str(env_named)})
            caches = cache_by_name(payload)

            self.assertEqual(caches["named_caches"]["path"], str(env_named))
            self.assertEqual(caches["named_caches"]["source"], "env:PANTS_NAMED_CACHES_DIR")

    def test_empty_pantsrc_files_list_disables_rc_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            declared_named, _ = configure_relative_caches(buildroot, pantsrc_files="[]")
            write_pantsrc(buildroot, Path(tmp) / "rc" / "named", Path(tmp) / "rc" / "store")

            rc_path = buildroot.parent / "home" / ".pants.rc"
            payload = run_helper(buildroot)

            # The rc file exists but must be neither consulted nor listed.
            self.assertEqual(cache_by_name(payload)["named_caches"]["path"], str(declared_named))
            self.assertNotIn(str(rc_path), payload["config_layers"])

    def test_apply_deletes_the_effective_cache_not_the_shadowed_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            declared_named, _ = configure_relative_caches(buildroot, pantsrc_files='["~/.pants.rc"]')
            declared_named.mkdir(parents=True)
            (declared_named / "stale.bin").write_bytes(b"x")

            live_named = Path(tmp) / "live" / "named"
            live_named.mkdir(parents=True)
            (live_named / "live.bin").write_bytes(b"x")
            write_pantsrc(buildroot, live_named, Path(tmp) / "live" / "store")

            run_helper(buildroot, "--limit", "named_caches=0", "--apply")

            self.assertFalse(live_named.exists())
            self.assertTrue(declared_named.exists())


class ShadowDetectionTest(unittest.TestCase):
    def test_abandoned_default_location_is_reported(self) -> None:
        """A repo that starts setting the option abandons the built-in default."""
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            configure_relative_caches(buildroot)

            home = buildroot.parent / "home"
            abandoned = home / ".cache" / "pants" / "named_caches"
            abandoned.mkdir(parents=True)
            (abandoned / "old.bin").write_bytes(b"x" * 16)

            payload = run_helper(buildroot)

            self.assertIn(str(abandoned), shadowed_paths(payload))
            self.assertTrue(abandoned.exists())

    def test_two_spellings_of_one_directory_are_not_reported_as_stale(self) -> None:
        """A symlinked home must not make the live cache look abandoned."""
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)

            real_cache = Path(tmp) / "real" / "named"
            real_cache.mkdir(parents=True)
            (real_cache / "cache.bin").write_bytes(b"x" * 8)
            link_dir = Path(tmp) / "linked"
            os.symlink(Path(tmp) / "real", link_dir)

            pants_toml = buildroot / "pants.toml"
            text = pants_toml.read_text(encoding="utf-8")
            text = text.replace(
                "[source]",
                f'named_caches_dir = "{(link_dir / "named").as_posix()}"\n'
                'pantsrc_files = ["~/.pants.rc"]\n\n[source]',
            )
            pants_toml.write_text(text, encoding="utf-8")
            write_pantsrc(buildroot, real_cache, Path(tmp) / "real" / "store")

            payload = run_helper(buildroot)

            self.assertEqual(shadowed_paths(payload), set())


class CacheSizingTest(unittest.TestCase):
    def test_hardlinked_content_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)
            (named_cache / "wheels").mkdir(parents=True)
            (named_cache / "venv").mkdir(parents=True)

            payload_file = named_cache / "wheels" / "wheel.bin"
            payload_file.write_bytes(b"x" * 4096)
            os.link(payload_file, named_cache / "venv" / "wheel.bin")

            named = cache_by_name(run_helper(buildroot))["named_caches"]

            self.assertEqual(named["file_count"], 2)
            self.assertEqual(named["size_bytes"], 4096)
            self.assertEqual(named["apparent_size_bytes"], 8192)

    def test_symlinked_cache_directory_is_measured(self) -> None:
        """Relocating a cache to another disk and leaving a symlink is normal."""
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)

            target = Path(tmp) / "elsewhere"
            target.mkdir(parents=True)
            (target / "cache.bin").write_bytes(b"x" * 256)
            named_cache.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, named_cache)

            named = cache_by_name(run_helper(buildroot))["named_caches"]

            self.assertTrue(named["exists"])
            self.assertEqual(named["size_bytes"], 256)

    def test_symlinked_cache_directory_is_never_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)

            target = Path(tmp) / "elsewhere"
            target.mkdir(parents=True)
            (target / "cache.bin").write_bytes(b"x" * 256)
            named_cache.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, named_cache)

            payload = run_helper(buildroot, "--limit", "named_caches=0", "--apply")

            self.assertEqual(cache_by_name(payload)["named_caches"]["action"], "skipped")
            self.assertTrue(target.exists())
            self.assertTrue((target / "cache.bin").exists())


class PexRootReportingTest(unittest.TestCase):
    def test_legacy_user_pex_root_is_reported_and_never_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)
            named_cache.mkdir(parents=True)
            (named_cache / "cache.bin").write_bytes(b"x" * 64)

            home = buildroot.parent / "home"
            legacy_pex = home / ".pex"
            legacy_pex.mkdir(parents=True)
            (legacy_pex / "wheel.bin").write_bytes(b"x" * 128)

            # named_caches really is over its limit here, so --apply deletes it;
            # the legacy pex root lives outside and must survive.
            payload = run_helper(buildroot, "--limit", "named_caches=0", "--apply")

            self.assertEqual(cache_by_name(payload)["named_caches"]["action"], "deleted")
            reported = {str(item["path"]) for item in payload["pex_roots"]}
            self.assertIn(str(legacy_pex), reported)
            self.assertTrue(legacy_pex.exists())

    def test_pex_root_env_var_with_tilde_is_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            configure_relative_caches(buildroot)

            home = buildroot.parent / "home"
            env_pex = home / "custom-pex"
            env_pex.mkdir(parents=True)
            (env_pex / "wheel.bin").write_bytes(b"x" * 32)

            payload = run_helper(buildroot, env={"PEX_ROOT": "~/custom-pex"})

            reported = {str(item["path"]) for item in payload["pex_roots"]}
            self.assertIn(str(env_pex), reported)

    def test_nested_pex_root_is_reported_before_its_parent_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)
            nested = named_cache / "pex_root"
            nested.mkdir(parents=True)
            (nested / "wheel.bin").write_bytes(b"x" * 512)

            payload = run_helper(buildroot, "--limit", "named_caches=0", "--apply")

            entries = {str(item["path"]): item for item in payload["pex_roots"]}
            self.assertIn(str(nested), entries)
            self.assertTrue(entries[str(nested)]["inside_named_caches"])
            self.assertGreater(entries[str(nested)]["size_bytes"], 0)
            # It goes with its parent; the report must have said so.
            self.assertFalse(nested.exists())
            self.assertIn("note", entries[str(nested)])


class ConfigResolutionEdgeCaseTest(unittest.TestCase):
    def test_xdg_cache_home_moves_the_default_locations(self) -> None:
        """Verified against a live Pants: its engine honors XDG_CACHE_HOME."""
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            # No cache options at all, so the defaults are what gets reported.
            pants_toml = buildroot / "pants.toml"
            text = pants_toml.read_text(encoding="utf-8")
            pants_toml.write_text(text.replace("[source]", "pantsrc_files = []\n\n[source]"), encoding="utf-8")

            xdg = Path(tmp) / "xdg"
            payload = run_helper(buildroot, env={"XDG_CACHE_HOME": str(xdg)})
            caches = cache_by_name(payload)

            self.assertEqual(caches["named_caches"]["path"], str(xdg / "pants" / "named_caches"))
            self.assertEqual(caches["local_store"]["path"], str(xdg / "pants" / "lmdb_store"))

    def test_pants_config_files_env_is_honored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            configure_relative_caches(buildroot)

            live = Path(tmp) / "fromlocal" / "named"
            (buildroot / "pants.local.toml").write_text(
                f'[GLOBAL]\nnamed_caches_dir = "{live.as_posix()}"\n', encoding="utf-8"
            )

            payload = run_helper(buildroot, env={"PANTS_CONFIG_FILES": "+['pants.local.toml']"})

            self.assertEqual(cache_by_name(payload)["named_caches"]["path"], str(live))

    def test_env_pantsrc_files_append_syntax_keeps_existing_rc(self) -> None:
        """`+[...]` extends; reading it as a replacement drops a live redirect."""
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            configure_relative_caches(buildroot, pantsrc_files='["~/.pants.rc"]')
            live_named = Path(tmp) / "rc" / "named"
            write_pantsrc(buildroot, live_named, Path(tmp) / "rc" / "store")

            extra = buildroot.parent / "home" / "extra.rc"
            extra.write_text("[GLOBAL]\n", encoding="utf-8")

            payload = run_helper(buildroot, env={"PANTS_PANTSRC_FILES": f"+['{extra.as_posix()}']"})

            self.assertEqual(cache_by_name(payload)["named_caches"]["path"], str(live_named))
            self.assertIn(str(extra), payload["config_layers"])

    def test_pantsrc_files_remove_disables_that_rc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            declared_named, _ = configure_relative_caches(
                buildroot, pantsrc_files='{ remove = ["~/.pants.rc"] }'
            )
            write_pantsrc(buildroot, Path(tmp) / "rc" / "named", Path(tmp) / "rc" / "store")

            payload = run_helper(buildroot)

            self.assertEqual(cache_by_name(payload)["named_caches"]["path"], str(declared_named))


class ApplySafetyTest(unittest.TestCase):
    def test_directory_containing_the_live_cache_is_not_called_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            parent = Path(tmp) / "cache"
            live = parent / "live"
            live.mkdir(parents=True)
            (live / "cache.bin").write_bytes(b"x" * 16)

            pants_toml = buildroot / "pants.toml"
            text = pants_toml.read_text(encoding="utf-8")
            pants_toml.write_text(
                text.replace(
                    "[source]",
                    f'named_caches_dir = "{parent.as_posix()}"\n'
                    'pantsrc_files = ["~/.pants.rc"]\n\n[source]',
                ),
                encoding="utf-8",
            )
            write_pantsrc(buildroot, live, Path(tmp) / "cache" / "store")

            payload = run_helper(buildroot)

            self.assertEqual(cache_by_name(payload)["named_caches"]["path"], str(live))
            self.assertNotIn(str(parent), shadowed_paths(payload))

    def test_unparseable_config_disables_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            named_cache, _ = configure_relative_caches(buildroot)
            named_cache.mkdir(parents=True)
            (named_cache / "cache.bin").write_bytes(b"x")
            (buildroot / "pants.toml").write_text("[GLOBAL\nbroken = ", encoding="utf-8")

            payload = run_helper(buildroot, "--limit", "named_caches=0", "--apply")

            self.assertFalse(payload["config_trusted"])
            self.assertFalse(payload["apply"])
            self.assertTrue(named_cache.exists())

    def test_unsupported_interpolation_disables_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            pants_toml = buildroot / "pants.toml"
            text = pants_toml.read_text(encoding="utf-8")
            pants_toml.write_text(
                text.replace(
                    "[source]",
                    'named_caches_dir = "%(pants_distdir)s/named"\npantsrc_files = []\n\n[source]',
                ),
                encoding="utf-8",
            )

            payload = run_helper(buildroot, "--limit", "named_caches=0", "--apply")

            self.assertFalse(payload["apply"])
            self.assertTrue(
                any("interpolation" in str(item) for item in payload["warnings"]),
                payload["warnings"],
            )


if __name__ == "__main__":
    unittest.main()
