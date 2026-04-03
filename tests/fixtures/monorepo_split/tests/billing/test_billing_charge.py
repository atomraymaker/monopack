import unittest

from app.billing.charge import run_charge
from functions.billing_charge import lambda_handler
import idna


class BillingChargeTests(unittest.TestCase):
    def test_lambda_handler_uses_billing_payload(self):
        response = lambda_handler({}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"], run_charge())

    def test_idna_available_for_billing_tests(self):
        self.assertTrue(hasattr(idna, "__version__"))


if __name__ == "__main__":
    unittest.main()
