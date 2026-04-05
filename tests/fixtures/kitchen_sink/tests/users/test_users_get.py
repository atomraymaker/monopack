import unittest

import colorama

from packs.users_get import lambda_handler


class UsersGetTests(unittest.TestCase):
    def test_handler_returns_expected_shape(self):
        response = lambda_handler({}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["feature"], "beta")

    def test_colorama_available_for_users_tests(self):
        self.assertTrue(hasattr(colorama, "__version__"))


if __name__ == "__main__":
    unittest.main()
