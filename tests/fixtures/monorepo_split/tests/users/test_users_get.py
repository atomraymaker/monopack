import unittest

from app.users.service import get_user_payload
from packs.users_get import lambda_handler
import colorama


class UsersGetTests(unittest.TestCase):
    def test_lambda_handler_uses_users_payload(self):
        response = lambda_handler({}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], get_user_payload())

    def test_colorama_available_for_users_tests(self):
        self.assertTrue(hasattr(colorama, "__version__"))


if __name__ == "__main__":
    unittest.main()
