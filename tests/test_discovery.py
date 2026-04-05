import tempfile
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monopack.discovery import discover_packs, resolve_pack_entrypoint


class DiscoveryTests(unittest.TestCase):
    def test_discover_packs_top_level_sorted_and_filtered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packs_dir = Path(tmpdir)
            (packs_dir / "zeta.py").write_text("", encoding="utf-8")
            (packs_dir / "alpha.py").write_text("", encoding="utf-8")
            (packs_dir / "_internal.py").write_text("", encoding="utf-8")
            (packs_dir / "notes.txt").write_text("", encoding="utf-8")
            nested = packs_dir / "nested"
            nested.mkdir()
            (nested / "child.py").write_text("", encoding="utf-8")

            result = discover_packs(packs_dir)

        self.assertEqual(result, ["alpha", "zeta"])

    def test_resolve_pack_entrypoint_returns_path_when_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packs_dir = Path(tmpdir)
            entrypoint = packs_dir / "runner.py"
            entrypoint.write_text("", encoding="utf-8")

            result = resolve_pack_entrypoint(packs_dir, "runner")

        self.assertEqual(result, entrypoint)

    def test_resolve_pack_entrypoint_raises_with_clear_message_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packs_dir = Path(tmpdir)

            with self.assertRaises(FileNotFoundError) as ctx:
                resolve_pack_entrypoint(packs_dir, "missing")

        self.assertIn("Pack 'missing' not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
