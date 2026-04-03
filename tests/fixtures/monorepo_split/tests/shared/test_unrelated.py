import unittest

import urllib3


class UnrelatedTests(unittest.TestCase):
    def test_unrelated_import(self):
        self.assertTrue(hasattr(urllib3, "__version__"))


if __name__ == "__main__":
    unittest.main()
