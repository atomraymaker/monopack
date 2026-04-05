import unittest

import idna

from packs.billing_charge import lambda_handler


class BillingChargeTests(unittest.TestCase):
    def test_handler_returns_expected_shape(self):
        response = lambda_handler({}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("charged:", response["body"])

    def test_idna_available_for_billing_tests(self):
        self.assertTrue(hasattr(idna, "__version__"))


if __name__ == "__main__":
    unittest.main()
