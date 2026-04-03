import tempfile
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.module_resolver import (
    module_name_from_path,
    parent_init_files,
    resolve_module_to_file,
)


class ModuleResolverTests(unittest.TestCase):
    def test_module_name_from_path_for_regular_module(self):
        project_root = Path("/tmp/project")
        path = project_root / "app" / "foo" / "bar.py"

        module = module_name_from_path(path, project_root)

        self.assertEqual(module, "app.foo.bar")

    def test_module_name_from_path_for_package_init(self):
        project_root = Path("/tmp/project")
        path = project_root / "app" / "foo" / "__init__.py"

        module = module_name_from_path(path, project_root)

        self.assertEqual(module, "app.foo")

    def test_resolve_module_to_file_prefers_module_file_over_package_init(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            module_file = project_root / "app" / "foo.py"
            package_init = project_root / "app" / "foo" / "__init__.py"
            module_file.parent.mkdir(parents=True)
            package_init.parent.mkdir(parents=True)
            module_file.write_text("", encoding="utf-8")
            package_init.write_text("", encoding="utf-8")

            resolved = resolve_module_to_file("app.foo", project_root)

        self.assertEqual(resolved, module_file)

    def test_resolve_module_to_file_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            resolved = resolve_module_to_file("app.missing", project_root)

        self.assertIsNone(resolved)

    def test_parent_init_files_returns_existing_files_in_package_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            app_init = project_root / "app" / "__init__.py"
            foo_init = project_root / "app" / "foo" / "__init__.py"
            module_path = project_root / "app" / "foo" / "bar" / "baz.py"

            app_init.parent.mkdir(parents=True)
            foo_init.parent.mkdir(parents=True)
            module_path.parent.mkdir(parents=True)
            app_init.write_text("", encoding="utf-8")
            foo_init.write_text("", encoding="utf-8")
            module_path.write_text("", encoding="utf-8")

            init_files = parent_init_files(module_path, project_root)

        self.assertEqual(init_files, [app_init, foo_init])


if __name__ == "__main__":
    unittest.main()
