import shutil
import tempfile
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.test_mode import (
    collect_third_party_roots_from_tests,
    copy_relevant_tests,
    module_names_from_files,
    test_file_is_relevant,
)


class TestModeHelpersTests(unittest.TestCase):
    def test_copy_relevant_tests_returns_none_when_tests_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            build_target = Path(tmpdir) / "build"
            project_root.mkdir()
            build_target.mkdir()

            copied = copy_relevant_tests(project_root, build_target, {"app.users.service"})

        self.assertIsNone(copied)

    def test_copy_relevant_tests_copies_only_relevant_tests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            build_target = Path(tmpdir) / "build"
            source_tests = project_root / "tests"
            source_tests.mkdir(parents=True)
            (source_tests / "test_users.py").write_text(
                "from app.users.service import version_payload\n",
                encoding="utf-8",
            )
            (source_tests / "test_billing.py").write_text(
                "from app.billing.charge import run_charge\n",
                encoding="utf-8",
            )
            build_target.mkdir()

            copied = copy_relevant_tests(project_root, build_target, {"app.users.service"})

            self.assertEqual(copied, build_target / "tests")
            self.assertTrue((build_target / "tests" / "test_users.py").is_file())
            self.assertFalse((build_target / "tests" / "test_billing.py").exists())

    def test_module_names_from_files_filters_first_party_paths(self):
        fixture_root = Path(__file__).resolve().parent / "fixtures" / "monorepo_split"

        files = {
            fixture_root / "functions" / "users_get.py",
            fixture_root / "app" / "users" / "service.py",
            fixture_root / "tests" / "users" / "test_users_get.py",
        }

        names = module_names_from_files(files, fixture_root)

        self.assertEqual(names, {"functions.users_get", "app.users.service"})

    def test_test_file_is_relevant_supports_parent_and_child_module_relations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tests_dir = Path(tmpdir)

            direct_test = tests_dir / "test_direct.py"
            direct_test.write_text("import app.users.service\n", encoding="utf-8")

            parent_test = tests_dir / "test_parent.py"
            parent_test.write_text("import app.users\n", encoding="utf-8")

            child_test = tests_dir / "test_child.py"
            child_test.write_text("import app.users.service.handlers\n", encoding="utf-8")

            unrelated_test = tests_dir / "test_unrelated.py"
            unrelated_test.write_text("import app.billing.charge\n", encoding="utf-8")

            selected = {"app.users.service"}

            self.assertTrue(test_file_is_relevant(direct_test, selected))
            self.assertTrue(test_file_is_relevant(parent_test, selected))
            self.assertTrue(test_file_is_relevant(child_test, selected))
            self.assertFalse(test_file_is_relevant(unrelated_test, selected))

    def test_collect_third_party_roots_from_tests_finds_non_stdlib_imports(self):
        fixture_root = Path(__file__).resolve().parent / "fixtures" / "test_mode"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            shutil.copytree(fixture_root, project_root)

            roots = collect_third_party_roots_from_tests(
                project_root / "tests",
                project_root,
            )

        self.assertEqual(roots, {"colorama"})


if __name__ == "__main__":
    unittest.main()
