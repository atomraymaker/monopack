from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.inline_config import InlineConfig, parse_inline_config, rewrite_inline_config


class InlineConfigTests(unittest.TestCase):
    def test_parse_inline_config_reads_known_keys_and_ignores_unknown(self):
        source = (
            "# monopack-start\n"
            "# extra_modules: app.beta, app.alpha, app.beta\n"
            "# ignored_key: should, be, ignored\n"
            "# extra_distributions: requests, PyYAML\n"
            "# monopack-end\n"
        )

        parsed = parse_inline_config(source)

        self.assertEqual(
            parsed,
            InlineConfig(
                extra_modules={"app.alpha", "app.beta"},
                extra_distributions={"PyYAML", "requests"},
            ),
        )

    def test_rewrite_inline_config_is_idempotent_and_sorts_values(self):
        source = (
            "# monopack-start\n"
            "# extra_distributions: requests, PyYAML\n"
            "# extra_modules: app.beta, app.alpha\n"
            "# monopack-end\n"
            "\n"
            "def lambda_handler(event, context):\n"
            "    return {}\n"
        )

        rewritten = rewrite_inline_config(source, parse_inline_config(source))
        rewritten_again = rewrite_inline_config(rewritten, parse_inline_config(rewritten))

        self.assertEqual(rewritten_again, rewritten)
        self.assertIn("# extra_distributions: PyYAML, requests\n", rewritten)
        self.assertIn("# extra_modules: app.alpha, app.beta\n", rewritten)

    def test_rewrite_inline_config_inserts_block_at_top_when_missing(self):
        source = "def lambda_handler(event, context):\n    return {}\n"

        rewritten = rewrite_inline_config(
            source,
            InlineConfig(
                extra_modules={"app.hidden.runtime_dep"},
                extra_distributions={"PyYAML"},
            ),
        )

        self.assertTrue(rewritten.startswith("# monopack-start\n"))
        self.assertIn("# extra_modules: app.hidden.runtime_dep\n", rewritten)


if __name__ == "__main__":
    unittest.main()
