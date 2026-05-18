from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install_skill.py"


class InstallSkillTest(unittest.TestCase):
    def run_installer(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(INSTALLER), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=check,
        )

    def test_dry_run_does_not_create_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            completed = self.run_installer(
                [
                    "--target-root",
                    str(target_root),
                    "--dry-run",
                ],
            )

            self.assertIn("Install skill:", completed.stdout)
            self.assertFalse((target_root / "pants").exists())

    def test_install_copies_skill_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            install_cmd = [
                "--target-root",
                str(target_root),
            ]

            self.run_installer(install_cmd)
            installed = target_root / "pants"
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "scripts" / "pants_repo_probe.py").is_file())

            completed = self.run_installer(
                install_cmd,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Target already exists:", completed.stderr)

    def test_force_replaces_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            installed = target_root / "pants"

            self.run_installer(["--target-root", str(target_root)])
            marker = installed / "local-only.txt"
            marker.write_text("old install", encoding="utf-8")

            self.run_installer(["--target-root", str(target_root), "--force"])

            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertFalse(marker.exists())

    def test_backup_preserves_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            installed = target_root / "pants"

            self.run_installer(["--target-root", str(target_root)])
            marker = installed / "local-only.txt"
            marker.write_text("old install", encoding="utf-8")

            self.run_installer(["--target-root", str(target_root), "--backup"])

            backups = sorted(target_root.glob("pants.backup.*"))
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "local-only.txt").is_file())
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertFalse(marker.exists())

    def test_runtime_defaults_use_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            generic_root = Path(tmp) / "generic-skills"
            codex_home = Path(tmp) / "codex-home"
            base_env = {key: value for key, value in os.environ.items() if key not in {"AGENT_SKILLS_DIR", "CODEX_HOME"}}

            env = {**base_env, "AGENT_SKILLS_DIR": str(generic_root)}
            self.run_installer([], env=env)
            self.assertTrue((generic_root / "pants" / "SKILL.md").is_file())

            env = {**base_env, "CODEX_HOME": str(codex_home)}
            self.run_installer(["--runtime", "codex"], env=env)
            self.assertTrue((codex_home / "skills" / "pants" / "SKILL.md").is_file())

    def test_copy_ignores_generated_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "custom-skill"
            target_root = Path(tmp) / "skills"
            (source / "scripts" / "__pycache__").mkdir(parents=True)
            (source / "SKILL.md").write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: custom-skill
                    description: fixture
                    ---
                    """
                ),
                encoding="utf-8",
            )
            (source / "scripts" / "helper.py").write_text("print('ok')\n", encoding="utf-8")
            (source / "scripts" / "__pycache__" / "helper.pyc").write_bytes(b"cached")

            self.run_installer(["--skill-dir", str(source), "--target-root", str(target_root)])

            installed = target_root / "custom-skill"
            self.assertTrue((installed / "scripts" / "helper.py").is_file())
            self.assertFalse((installed / "scripts" / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
