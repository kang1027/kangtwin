"""텔레그램 Bot API 최소 클라이언트 (long polling)."""
import http.client
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

Buttons = List[List[Tuple[str, str]]]


class TelegramError(Exception):
    pass


class Bot:
    def __init__(self, token: str, opener=urllib.request.urlopen):
        self._token = token
        self._opener = opener

    def _call(self, method: str, body: Dict[str, Any], timeout: int = 30) -> Any:
        url = "https://api.telegram.org/bot%s/%s" % (self._token, method)
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener(req, timeout=timeout) as res:
                payload = json.loads(res.read().decode())
        except urllib.error.HTTPError as e:
            raise TelegramError("%s failed: HTTP %s" % (method, e.code)) from None
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            reason = str(getattr(e, "reason", e)).replace(self._token, "***")
            raise TelegramError("%s failed: %s" % (method, reason)) from None
        if not payload.get("ok"):
            raise TelegramError("%s failed: %s" % (method, payload.get("description", "not ok")))
        return payload.get("result")

    def send_message(self, chat_id: int, text: str, buttons: Optional[Buttons] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if buttons:
            body["reply_markup"] = {
                "inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons],
            }
        return self._call("sendMessage", body)

    def get_updates(self, offset: Optional[int], timeout: int = 50) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            body["offset"] = offset
        return self._call("getUpdates", body, timeout=timeout + 10) or []

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    def clear_buttons(self, chat_id: int, message_id: int) -> None:
        self._call("editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []},
        })
