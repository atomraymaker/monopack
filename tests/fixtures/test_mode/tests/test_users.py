import unittest

from app.users.service import version_payload
import colorama


class UsersTests(unittest.TestCase):
    def test_version_payload_uses_packaged_code(self):
        self.assertIsInstance(version_payload(), str)

    def test_colorama_is_importable_for_test_mode(self):
        self.assertTrue(hasattr(colorama, "__version__"))


if __name__ == "__main__":
    unittest.main()
