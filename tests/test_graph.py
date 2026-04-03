import shutil
import tempfile
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.graph import collect_reachable_first_party_files
from monopack.graph import resolve_relative_import_base_module


class GraphTests(unittest.TestCase):
    def test_resolve_relative_import_base_module_handles_current_package(self):
        base = resolve_relative_import_base_module(
            current_module="app.services.users",
            level=1,
            module=None,
        )

        self.assertEqual(base, "app.services")

    def test_resolve_relative_import_base_module_handles_parent_levels(self):
        base = resolve_relative_import_base_module(
            current_module="app.services.users",
            level=2,
            module="shared",
        )

        self.assertEqual(base, "app.shared")

    def test_resolve_relative_import_base_module_returns_none_when_level_too_high(self):
        base = resolve_relative_import_base_module(
            current_module="app.services.users",
            level=4,
            module="shared",
        )

        self.assertIsNone(base)

    def test_resolve_relative_import_base_module_for_package_init_uses_package(self):
        base = resolve_relative_import_base_module(
            current_module="app.services",
            level=1,
            module="users",
            is_package=True,
        )

        self.assertEqual(base, "app.services.users")

    def test_collect_reachable_first_party_files_recurses_and_includes_parent_inits(self):
        fixture_root = Path(__file__).resolve().parent / "fixtures" / "shared_code"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            shutil.copytree(fixture_root, project_root)

            files_to_copy, third_party_roots = collect_reachable_first_party_files(
                entrypoint_module="functions.users_get",
                entrypoint_file=project_root / "functions" / "users_get.py",
                project_root=project_root,
                first_party_roots={"functions", "app", "lib"},
            )

        relative_paths = {
            path.relative_to(project_root).as_posix()
            for path in files_to_copy
        }

        self.assertEqual(
            relative_paths,
            {
                "functions/__init__.py",
                "functions/users_get.py",
                "app/__init__.py",
                "app/users/__init__.py",
                "app/users/service.py",
                "app/shared/__init__.py",
                "app/shared/auth.py",
            },
        )
        self.assertEqual(third_party_roots, set())

    def test_collect_reachable_first_party_files_unions_third_party_roots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            entrypoint = project_root / "functions" / "users_get.py"
            app_module = project_root / "app" / "users" / "service.py"
            shared_module = project_root / "app" / "shared" / "auth.py"

            entrypoint.parent.mkdir(parents=True)
            app_module.parent.mkdir(parents=True)
            shared_module.parent.mkdir(parents=True)

            entrypoint.write_text("import app.users.service\n", encoding="utf-8")
            app_module.write_text(
                "import requests\nimport app.shared.auth\n",
                encoding="utf-8",
            )
            shared_module.write_text("import boto3\n", encoding="utf-8")

            files_to_copy, third_party_roots = collect_reachable_first_party_files(
                entrypoint_module="functions.users_get",
                entrypoint_file=entrypoint,
                project_root=project_root,
                first_party_roots={"functions", "app", "lib"},
            )

            relative_paths = {
                path.relative_to(project_root).as_posix()
                for path in files_to_copy
            }

        self.assertIn("functions/users_get.py", relative_paths)
        self.assertIn("app/users/service.py", relative_paths)
        self.assertIn("app/shared/auth.py", relative_paths)
        self.assertEqual(third_party_roots, {"requests", "boto3"})

    def test_collect_reachable_first_party_files_resolves_relative_imports(self):
        fixture_root = Path(__file__).resolve().parent / "fixtures" / "relative_imports"

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            shutil.copytree(fixture_root, project_root)

            files_to_copy, third_party_roots = collect_reachable_first_party_files(
                entrypoint_module="functions.users_get",
                entrypoint_file=project_root / "functions" / "users_get.py",
                project_root=project_root,
                first_party_roots={"functions", "app", "lib"},
            )

        relative_paths = {
            path.relative_to(project_root).as_posix()
            for path in files_to_copy
        }

        self.assertEqual(
            relative_paths,
            {
                "functions/__init__.py",
                "functions/users_get.py",
                "app/__init__.py",
                "app/handlers/__init__.py",
                "app/handlers/user_handler.py",
                "app/services/__init__.py",
                "app/services/users.py",
                "app/services/profile.py",
                "app/shared/__init__.py",
                "app/shared/auth.py",
                "app/shared/tokens.py",
            },
        )
        self.assertEqual(third_party_roots, set())

    def test_collect_reachable_first_party_files_includes_existing_extra_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            entrypoint = project_root / "functions" / "users_get.py"
            extra_module = project_root / "app" / "hidden" / "runtime_dep.py"

            entrypoint.parent.mkdir(parents=True)
            extra_module.parent.mkdir(parents=True)

            entrypoint.write_text(
                "def lambda_handler(event, context):\n    return {}\n",
                encoding="utf-8",
            )
            extra_module.write_text("VALUE = 'ok'\n", encoding="utf-8")

            files_to_copy, _ = collect_reachable_first_party_files(
                entrypoint_module="functions.users_get",
                entrypoint_file=entrypoint,
                project_root=project_root,
                first_party_roots={"functions", "app", "lib"},
                extra_modules={"app.hidden.runtime_dep", "app.missing.nope", "requests"},
            )

            relative_paths = {
                path.relative_to(project_root).as_posix()
                for path in files_to_copy
            }

        self.assertIn("functions/users_get.py", relative_paths)
        self.assertIn("app/hidden/runtime_dep.py", relative_paths)


if __name__ == "__main__":
    unittest.main()
