import sys
import tomllib
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class PackageImportTests(unittest.TestCase):
    def test_package_import_exposes_version(self):
        import monopack

        self.assertTrue(hasattr(monopack, "__version__"))
        self.assertIsInstance(monopack.__version__, str)

    def test_package_version_matches_pyproject(self):
        import monopack

        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        with pyproject_path.open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)

        self.assertEqual(monopack.__version__, pyproject["project"]["version"])


if __name__ == "__main__":
    unittest.main()
