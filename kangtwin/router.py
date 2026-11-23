"""텔레그램 업데이트 하나를 실행할 행동 목록으로 바꾼다. 부수 효과 없음."""
import hmac
from typing import Any, Dict, List, Optional, Tuple

Action = Tuple[str, Dict[str, Any]]

CALLBACKS = {
    "skip": ("interview_close", {"reason": "skip"}),
    "later": ("interview_close", {"reason": "later"}),
    "apply": ("interview_apply", {}),
    "revise": ("interview_mark_revise", {}),
    "drop": ("interview_close", {"reason": "drop"}),
    "more": ("interview_more", {}),
}


def _callback(cb: Dict[str, Any], chat_id: int, interview: Dict[str, Any]) -> List[Action]:
    msg = cb.get("message") or {}
    actions: List[Action] = [("ack", {"callback_id": cb.get("id"), "chat_id": chat_id,
                                      "message_id": msg.get("message_id")})]
    parts = (cb.get("data") or "").split(":")
    if parts[0] == "bt":
        if len(parts) == 4 and parts[2].isdigit() and parts[3] in ("me", "clone"):
            actions.append(("blind_answer", {"text": ":".join(parts[1:])}))
        return actions
    if len(parts) != 3 or parts[0] != "iv" or parts[1] not in CALLBACKS:
        return actions
    if parts[2] != interview.get("id"):
        actions.append(("reply", {"text": "지난 질문 버튼임. 지금 건 새 메시지에서 눌러줘"}))
        return actions
    name, extra = CALLBACKS[parts[1]]
    actions.append((name, dict(extra, id=parts[2])))
    return actions


def route(update: Dict[str, Any], owner: Optional[int], interview: Dict[str, Any],
          pairing_code: Optional[str]) -> List[Action]:
    if "callback_query" in update:
        cb = update["callback_query"]
        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
        if owner is None or chat_id != owner:
            return []
        return _callback(cb, chat_id, interview)

    msg = update.get("message")
    if not msg:
        return []
    chat_id = (msg.get("chat") or {}).get("id")
    body = (msg.get("text") or "").strip()

    if owner is None or chat_id != owner:
        if owner is None and pairing_code and hmac.compare_digest(body, "/start %s" % pairing_code):
            return [("pair", {"chat_id": chat_id})]
        return []

    if not body:
        return []
    if body == "/ask":
        return [("interview_ask", {})]
    if body == "/status":
        return [("status", {})]
    if body == "/contests":
        return [("contest_scout", {})]
    if body == "/funds":
        return [("fund_scout", {})]
    if body == "/blind":
        return [("blind_start", {})]
    status = interview.get("status")
    if status == "awaiting_answer":
        return [("interview_answer", {"text": body})]
    if status == "revising":
        return [("interview_revise", {"text": body})]
    return [("memo", {"text": body})]
