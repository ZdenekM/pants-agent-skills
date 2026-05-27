from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "skills" / "pants" / "scripts" / "pants_repo_probe.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "minimal-python-pants"


def write_fake_pants_runner(buildroot: Path) -> str:
    fake_pants = buildroot / "fake_pants.py"
    fake_pants.write_text(
        textwrap.dedent(
            """\
            from __future__ import annotations

            import sys

            if sys.argv[1:] == ["--version"]:
                print("2.31.0")
            elif sys.argv[1:] == ["roots"]:
                print("src")
                print("tests")
            else:
                print(f"unexpected command: {' '.join(sys.argv[1:])}", file=sys.stderr)
                raise SystemExit(64)
            """
        ),
        encoding="utf-8",
    )

    if os.name == "nt":
        runner = buildroot / "pants.bat"
        runner.write_text(f'@echo off\r\n"{sys.executable}" "%~dp0fake_pants.py" %*\r\n', encoding="utf-8")
        return "./pants.bat"

    runner = buildroot / "pants"
    runner.write_text(f"#!{sys.executable}\nexec(open({str(fake_pants)!r}).read())\n", encoding="utf-8")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    return "./pants"


def write_failing_pants_runner(buildroot: Path) -> None:
    if os.name == "nt":
        runner = buildroot / "pants.bat"
        runner.write_text("@echo off\r\nexit /b 64\r\n", encoding="utf-8")
        return

    runner = buildroot / "pants"
    runner.write_text(f"#!{sys.executable}\nraise SystemExit(64)\n", encoding="utf-8")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)


class PantsRepoProbeTest(unittest.TestCase):
    def test_probe_discovers_buildroot_and_uses_local_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            nested = buildroot / "src" / "example"
            expected_runner = write_fake_pants_runner(buildroot)

            completed = subprocess.run(
                [sys.executable, str(PROBE), "--cwd", str(nested), "--timeout", "1"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["buildroot"], str(buildroot))
            self.assertEqual(payload["runner"], expected_runner)
            self.assertEqual(payload["pants_version"], "2.31.0")
            self.assertEqual(payload["source_roots"], ["src", "tests"])
            self.assertIn("pants.backend.python", payload["backends"])
            self.assertEqual(
                payload["python"]["resolves"],
                {"python-default": "3rdparty/python/default.lock"},
            )
            self.assertEqual(payload["warnings"], [])

    def test_files_only_skips_pants_commands_but_parses_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            write_failing_pants_runner(buildroot)

            completed = subprocess.run(
                [sys.executable, str(PROBE), "--cwd", str(buildroot), "--files-only"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["pants_version"], "2.31.0")
            self.assertEqual(payload["source_roots"], ["src", "tests"])
            self.assertIn("pants.backend.python", payload["backends"])
            self.assertEqual(payload["warnings"], [])

    def test_files_only_does_not_require_pants_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buildroot = Path(tmp) / "repo"
            shutil.copytree(FIXTURE, buildroot)
            env = os.environ.copy()
            env["PATH"] = str(buildroot / "missing-bin")

            completed = subprocess.run(
                [sys.executable, str(PROBE), "--cwd", str(buildroot), "--files-only"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["pants_version"], "2.31.0")
            self.assertEqual(payload["source_roots"], ["src", "tests"])
            self.assertEqual(payload["runner"], "pants")
            self.assertEqual(payload["warnings"], [])

    def test_legacy_skip_pants_commands_flag_is_not_supported(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PROBE), "--skip-pants-commands"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("unrecognized arguments: --skip-pants-commands", completed.stderr)

    def test_probe_reports_missing_buildroot_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [sys.executable, str(PROBE), "--cwd", tmp],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(completed.returncode, 2)
            payload = json.loads(completed.stdout)
            self.assertIsNone(payload["buildroot"])
            self.assertTrue(payload["warnings"])


if __name__ == "__main__":
    unittest.main()
