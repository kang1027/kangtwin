import unittest

from kangtwin.router import route

OWNER = 1001
STRANGER = 2002


def text(chat, body, uid=1):
    return {"update_id": uid, "message": {"message_id": 5, "chat": {"id": chat}, "text": body}}


def callback(chat, data, uid=1):
    return {"update_id": uid, "callback_query": {
        "id": "cb9", "data": data, "message": {"message_id": 6, "chat": {"id": chat}}}}


AWAIT = {"id": "a1", "status": "awaiting_answer"}
PROPOSED = {"id": "a1", "status": "proposed"}
REVISING = {"id": "a1", "status": "revising"}


class RouterTest(unittest.TestCase):
    def test_contests_command_runs_contest_scout(self):
        self.assertEqual(route(text(OWNER, "/contests"), OWNER, {}, None), [("contest_scout", {})])

    def test_funds_command_runs_fund_scout(self):
        self.assertEqual(route(text(OWNER, "/funds"), OWNER, {}, None), [("fund_scout", {})])

    def test_jobs_command_is_a_memo(self):
        self.assertEqual(route(text(OWNER, "/jobs"), OWNER, {}, None), [("memo", {"text": "/jobs"})])

    def test_pairing_with_right_code(self):
        self.assertEqual(route(text(STRANGER, "/start 482913"), None, {}, "482913"),
                         [("pair", {"chat_id": STRANGER})])

    def test_pairing_with_wrong_code_is_ignored(self):
        self.assertEqual(route(text(STRANGER, "/start 000000"), None, {}, "482913"), [])

    def test_pairing_without_issued_code_is_ignored(self):
        self.assertEqual(route(text(STRANGER, "/start "), None, {}, None), [])

    def test_stranger_after_pairing_is_ignored(self):
        self.assertEqual(route(text(STRANGER, "/start 482913"), OWNER, AWAIT, "482913"), [])
        self.assertEqual(route(text(STRANGER, "안녕"), OWNER, AWAIT, None), [])

    def test_forged_callback_from_stranger_is_ignored(self):
        self.assertEqual(route(callback(STRANGER, "iv:apply:a1"), OWNER, PROPOSED, None), [])

    def test_ask_and_status_commands(self):
        self.assertEqual(route(text(OWNER, "/ask"), OWNER, {}, None), [("interview_ask", {})])
        self.assertEqual(route(text(OWNER, "/status"), OWNER, {}, None), [("status", {})])

    def test_answer_while_awaiting(self):
        self.assertEqual(route(text(OWNER, "게임 동아리"), OWNER, AWAIT, None),
                         [("interview_answer", {"text": "게임 동아리"})])

    def test_text_while_revising(self):
        self.assertEqual(route(text(OWNER, "두 번째 줄 빼"), OWNER, REVISING, None),
                         [("interview_revise", {"text": "두 번째 줄 빼"})])

    def test_text_without_session_is_memo(self):
        self.assertEqual(route(text(OWNER, "오늘 Sprout 펌웨어 고침"), OWNER, {"status": "closed"}, None),
                         [("memo", {"text": "오늘 Sprout 펌웨어 고침"})])

    def test_text_while_proposed_is_memo(self):
        self.assertEqual(route(text(OWNER, "아 그리고"), OWNER, PROPOSED, None),
                         [("memo", {"text": "아 그리고"})])

    def test_callbacks_map_to_actions_with_ack_first(self):
        cases = {
            "iv:skip:a1": ("interview_close", {"id": "a1", "reason": "skip"}),
            "iv:later:a1": ("interview_close", {"id": "a1", "reason": "later"}),
            "iv:apply:a1": ("interview_apply", {"id": "a1"}),
            "iv:revise:a1": ("interview_mark_revise", {"id": "a1"}),
            "iv:drop:a1": ("interview_close", {"id": "a1", "reason": "drop"}),
            "iv:more:a1": ("interview_more", {"id": "a1"}),
        }
        for data, action in cases.items():
            actions = route(callback(OWNER, data), OWNER, PROPOSED, None)
            self.assertEqual(actions[0], ("ack", {"callback_id": "cb9", "chat_id": OWNER, "message_id": 6}), data)
            self.assertEqual(actions[1], action, data)

    def test_callback_for_old_interview_gets_reply(self):
        actions = route(callback(OWNER, "iv:apply:old"), OWNER, PROPOSED, None)
        self.assertEqual(actions[1][0], "reply")

    def test_unknown_callback_is_only_acked(self):
        actions = route(callback(OWNER, "zz:what"), OWNER, PROPOSED, None)
        self.assertEqual([a[0] for a in actions], ["ack"])

    def test_update_without_message_is_ignored(self):
        self.assertEqual(route({"update_id": 3, "edited_message": {}}, OWNER, AWAIT, None), [])


if __name__ == "__main__":
    unittest.main()
