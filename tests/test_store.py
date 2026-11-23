import os
import tempfile
import unittest
from unittest import mock

from kangtwin import store


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"KANGTWIN_STATE": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_save_then_load_round_trip(self):
        store.save("owner", {"chat_id": 42, "이름": "서윤"})
        self.assertEqual(store.load("owner", None), {"chat_id": 42, "이름": "서윤"})

    def test_missing_file_returns_default(self):
        self.assertEqual(store.load("nothing", {"a": 1}), {"a": 1})

    def test_corrupt_json_returns_default(self):
        with open(os.path.join(self.tmp.name, "broken.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(store.load("broken", []), [])

    def test_second_lock_is_busy(self):
        with store.lock("interview"):
            with self.assertRaises(store.Busy):
                with store.lock("interview"):
                    pass

    def test_lock_released_after_block(self):
        with store.lock("interview"):
            pass
        with store.lock("interview"):
            pass


if __name__ == "__main__":
    unittest.main()
