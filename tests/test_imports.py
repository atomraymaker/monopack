import tempfile
from pathlib import Path
import sys
import textwrap
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.imports import (
    RelativeImportRef,
    classify_roots,
    extract_import_references_from_file,
    extract_imports_from_file,
    root_module,
)


class ImportParsingTests(unittest.TestCase):
    def test_extract_import_references_from_file_includes_relative_import_details(self):
        source = textwrap.dedent(
            """
            import os
            from app.handlers import users
            from .service import get_user
            from ..shared import auth
            from . import sibling
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text(source, encoding="utf-8")

            refs = extract_import_references_from_file(path)

        absolute_modules = {ref.module for ref in refs if ref.level == 0}
        relative_refs = [ref for ref in refs if ref.level > 0]

        self.assertEqual(absolute_modules, {"os", "app.handlers"})
        self.assertEqual(
            relative_refs,
            [
                RelativeImportRef(level=1, module="service", imported_names=("get_user",)),
                RelativeImportRef(level=2, module="shared", imported_names=("auth",)),
                RelativeImportRef(level=1, module=None, imported_names=("sibling",)),
            ],
        )

    def test_extract_imports_from_file_collects_absolute_import_modules(self):
        source = textwrap.dedent(
            """
            import os
            import requests.sessions
            import pkg.sub as alias
            from collections import Counter
            from urllib.parse import urlparse
            from .local import thing
            from ..parent import other
            from . import sibling
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text(source, encoding="utf-8")

            modules = extract_imports_from_file(path)

        self.assertEqual(
            modules,
            {
                "os",
                "requests.sessions",
                "pkg.sub",
                "collections",
                "urllib.parse",
            },
        )

    def test_extract_imports_from_file_excludes_type_checking_imports(self):
        source = textwrap.dedent(
            """
            import json
            from app.users import service

            if TYPE_CHECKING:
                import boto3
                from app.internal import types

            if typing.TYPE_CHECKING:
                import botocore
                from .local_types import Alias

            if False:
                import idna
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text(source, encoding="utf-8")

            modules = extract_imports_from_file(path)

        self.assertEqual(modules, {"json", "app.users", "idna"})

    def test_extract_imports_from_file_includes_literal_dynamic_import_calls(self):
        source = textwrap.dedent(
            """
            import importlib

            requests = importlib.import_module("requests")
            runtime_dep = importlib.import_module("app.hidden.runtime_dep")
            yaml = __import__("yaml")
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text(source, encoding="utf-8")

            modules = extract_imports_from_file(path)

        self.assertEqual(
            modules,
            {
                "importlib",
                "requests",
                "app.hidden.runtime_dep",
                "yaml",
            },
        )

    def test_extract_imports_from_file_ignores_non_literal_dynamic_import_calls(self):
        source = textwrap.dedent(
            """
            import importlib

            name = "requests"
            f_name = "idna"

            importlib.import_module(name)
            __import__(name)
            importlib.import_module(f"pkg.{f_name}")
            __import__("pkg." + f_name)
            importlib.import_module(resolve_name())
            __import__(build_name())
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text(source, encoding="utf-8")

            modules = extract_imports_from_file(path)

        self.assertEqual(modules, {"importlib"})

    def test_extract_import_references_from_file_keeps_else_branch_under_type_checking_guard(self):
        source = textwrap.dedent(
            """
            if TYPE_CHECKING:
                from .type_only import helper
            else:
                from .runtime import helper
            """
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text(source, encoding="utf-8")

            refs = extract_import_references_from_file(path)

        self.assertEqual(
            refs,
            [RelativeImportRef(level=1, module="runtime", imported_names=("helper",))],
        )

    def test_root_module_returns_first_segment(self):
        self.assertEqual(root_module("json"), "json")
        self.assertEqual(root_module("urllib.parse"), "urllib")

    def test_classify_roots_splits_first_party_stdlib_and_third_party(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "monopack").mkdir()
            (project_root / "monopack" / "cli.py").write_text("VALUE = 1\n", encoding="utf-8")

            modules = {
                "monopack.cli",
                "json",
                "pathlib",
                "requests.sessions",
            }

            first_party, stdlib, third_party = classify_roots(modules, project_root)

        self.assertEqual(first_party, {"monopack"})
        self.assertEqual(stdlib, {"json", "pathlib"})
        self.assertEqual(third_party, {"requests"})


if __name__ == "__main__":
    unittest.main()
