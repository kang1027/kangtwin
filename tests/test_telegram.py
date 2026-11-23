import io
import json
import unittest
import urllib.error
import urllib.parse

from kangtwin.telegram import Bot, TelegramError

TOKEN = "123456:SECRET-TOKEN"


class FakeOpener:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {"ok": True, "result": {}}
        self.error = error
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append((req.full_url, req.data, timeout))
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.payload).encode())


def sent_body(opener):
    return json.loads(opener.calls[-1][1].decode())


class BotTest(unittest.TestCase):
    def test_send_message_hits_send_message_method(self):
        opener = FakeOpener({"ok": True, "result": {"message_id": 7}})
        result = Bot(TOKEN, opener=opener).send_message(42, "안녕")
        self.assertTrue(opener.calls[-1][0].endswith("/sendMessage"))
        self.assertEqual(sent_body(opener)["chat_id"], 42)
        self.assertEqual(sent_body(opener)["text"], "안녕")
        self.assertEqual(result["message_id"], 7)

    def test_buttons_become_inline_keyboard_rows(self):
        opener = FakeOpener()
        Bot(TOKEN, opener=opener).send_message(42, "q", buttons=[[("반영", "iv:apply:a1"), ("버리기", "iv:drop:a1")]])
        markup = sent_body(opener)["reply_markup"]
        self.assertEqual(markup["inline_keyboard"][0][0], {"text": "반영", "callback_data": "iv:apply:a1"})
        self.assertEqual(len(markup["inline_keyboard"][0]), 2)

    def test_get_updates_passes_offset_and_returns_list(self):
        opener = FakeOpener({"ok": True, "result": [{"update_id": 5}]})
        updates = Bot(TOKEN, opener=opener).get_updates(offset=5, timeout=1)
        self.assertEqual(updates, [{"update_id": 5}])
        self.assertEqual(sent_body(opener)["offset"], 5)

    def test_not_ok_raises(self):
        opener = FakeOpener({"ok": False, "description": "Bad Request: chat not found"})
        with self.assertRaises(TelegramError):
            Bot(TOKEN, opener=opener).send_message(1, "x")

    def test_http_error_message_hides_token(self):
        url = "https://api.telegram.org/bot%s/getUpdates" % TOKEN
        err = urllib.error.HTTPError(url, 409, "Conflict", {}, io.BytesIO(b'{"ok":false}'))
        with self.assertRaises(TelegramError) as ctx:
            Bot(TOKEN, opener=FakeOpener(error=err)).get_updates(None, timeout=1)
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertIn("409", str(ctx.exception))

    def test_network_error_message_hides_token(self):
        err = urllib.error.URLError("timed out for bot%s" % TOKEN)
        with self.assertRaises(TelegramError) as ctx:
            Bot(TOKEN, opener=FakeOpener(error=err)).send_message(1, "x")
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_incomplete_read_becomes_telegram_error(self):
        import http.client
        with self.assertRaises(TelegramError):
            Bot(TOKEN, opener=FakeOpener(error=http.client.IncompleteRead(b""))).get_updates(None, timeout=1)

    def test_clear_buttons_sends_empty_keyboard(self):
        opener = FakeOpener()
        Bot(TOKEN, opener=opener).clear_buttons(42, 9)
        self.assertTrue(opener.calls[-1][0].endswith("/editMessageReplyMarkup"))
        self.assertEqual(sent_body(opener)["reply_markup"], {"inline_keyboard": []})

    def test_answer_callback(self):
        opener = FakeOpener({"ok": True, "result": True})
        Bot(TOKEN, opener=opener).answer_callback("cb1", "ㅇㅋ")
        self.assertTrue(opener.calls[-1][0].endswith("/answerCallbackQuery"))
        self.assertEqual(sent_body(opener)["callback_query_id"], "cb1")


if __name__ == "__main__":
    unittest.main()
