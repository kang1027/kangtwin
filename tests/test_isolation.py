import unittest

from kangtwin import config


class IsolationTest(unittest.TestCase):
    def test_tests_never_point_at_the_real_vault(self):
        self.assertNotIn("Mobile Documents", str(config.VAULT),
                         "python3 -m unittest discover -s tests -t . 로 실행해야 함")


if __name__ == "__main__":
    unittest.main()
