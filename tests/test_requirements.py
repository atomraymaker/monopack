import tempfile
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.requirements import (
    filter_requirements_for_distributions,
    parse_pinned_requirements,
)


class RequirementsTests(unittest.TestCase):
    def test_parse_pinned_requirements_parses_and_normalizes_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            requirements_path = Path(tmpdir) / "requirements.txt"
            requirements_path.write_text(
                "\n"
                "# comment\n"
                "Requests == 2.31.0\n"
                "my_pkg==1.2.3\n"
                "  # indented comment\n",
                encoding="utf-8",
            )

            parsed = parse_pinned_requirements(requirements_path)

        self.assertEqual(
            parsed,
            {
                "requests": "Requests==2.31.0",
                "my-pkg": "my_pkg==1.2.3",
            },
        )

    def test_parse_pinned_requirements_rejects_unsupported_forms_with_line_number(self):
        invalid_lines = [
            "requests>=2.0",
            "requests[socks]==2.31.0",
            "-r base.txt",
            "-e .",
            "git+https://github.com/pallets/flask.git",
        ]

        for invalid_line in invalid_lines:
            with self.subTest(invalid_line=invalid_line):
                with tempfile.TemporaryDirectory() as tmpdir:
                    requirements_path = Path(tmpdir) / "requirements.txt"
                    requirements_path.write_text(
                        f"ok_pkg==1.0.0\n{invalid_line}\n",
                        encoding="utf-8",
                    )

                    with self.assertRaisesRegex(
                        ValueError,
                        r"line 2",
                    ):
                        parse_pinned_requirements(requirements_path)

    def test_filter_requirements_for_distributions_returns_sorted_matches(self):
        parsed = {
            "requests": "Requests==2.31.0",
            "pyyaml": "PyYAML==6.0.2",
            "my-pkg": "my_pkg==1.2.3",
        }

        filtered = filter_requirements_for_distributions(
            parsed,
            {"MY_PKG", "pyyaml"},
        )

        self.assertEqual(filtered, ["PyYAML==6.0.2", "my_pkg==1.2.3"])

    def test_filter_requirements_for_distributions_raises_keyerror_for_missing(self):
        parsed = {"requests": "Requests==2.31.0"}

        with self.assertRaisesRegex(
            KeyError,
            r"Missing pinned requirements for distributions: flask, py-yaml",
        ):
            filter_requirements_for_distributions(parsed, {"Flask", "PY_YAML"})


if __name__ == "__main__":
    unittest.main()
