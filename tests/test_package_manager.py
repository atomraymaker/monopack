from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.package_manager import (
    detect_package_manager_candidates,
    resolve_package_manager,
)


class PackageManagerTests(unittest.TestCase):
    def test_detect_package_manager_candidates_from_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "uv.lock").write_text("", encoding="utf-8")
            (project_root / "Pipfile.lock").write_text("{}", encoding="utf-8")

            candidates = detect_package_manager_candidates(project_root)

        self.assertEqual(candidates, {"uv", "pipenv"})

    def test_resolve_package_manager_returns_explicit_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            resolved = resolve_package_manager(project_root, "poetry")

        self.assertEqual(resolved, "poetry")

    def test_resolve_package_manager_auto_detects_single_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")

            resolved = resolve_package_manager(project_root, "auto")

        self.assertEqual(resolved, "pip")

    def test_resolve_package_manager_auto_detects_poetry_from_pyproject(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "pyproject.toml").write_text(
                "[tool.poetry]\nname='demo'\nversion='0.1.0'\n",
                encoding="utf-8",
            )

            resolved = resolve_package_manager(project_root, "auto")

        self.assertEqual(resolved, "poetry")

    def test_resolve_package_manager_auto_fails_when_ambiguous(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "requirements.txt").write_text("", encoding="utf-8")
            (project_root / "uv.lock").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "Could not auto-detect a unique package manager",
            ):
                resolve_package_manager(project_root, "auto")

    def test_resolve_package_manager_auto_fails_when_no_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            with self.assertRaisesRegex(
                ValueError,
                "Could not auto-detect a package manager",
            ):
                resolve_package_manager(project_root, "auto")


if __name__ == "__main__":
    unittest.main()
