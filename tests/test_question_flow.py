"""Answers must return to the exact request and must never become a second task."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_session import Codex
from test_parallel_chats import FakeAppServer


class QuestionFlowTests(unittest.TestCase):
    def setUp(self):
        workspace = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch("codex_session.AppServer", FakeAppServer))
        self.codex = Codex(Path(workspace), "fake")
        self.rpc = self.codex._rpc
        self.codex.start_prompt("ask", submission="first", expected_thread=None)
        self.thread, self.turn = self.rpc.started.get(timeout=2)

    def ask(self, questions=None):
        self.rpc.request("server-request-7", {
            "threadId": self.thread, "turnId": self.turn, "itemId": "question-item", "isBlocking": True,
            "questions": questions or [
                {"id": "size", "header": "尺寸", "question": "选哪个尺寸？", "options": [
                    {"label": "上屏", "description": "1920x1080"}, {"label": "下屏", "description": "1280x960"}]},
                {"id": "style", "header": "风格", "question": "希望什么风格？", "options": None},
            ],
        })
        return self.codex.snapshot()["question"]["id"]

    def answer(self, ident, action, **kwargs):
        self.codex.answer_question(self.thread, ident, action, **kwargs)

    def test_multi_question_reply_is_scoped_and_idempotent(self):
        ident = self.ask()
        with self.assertRaisesRegex(ValueError, "全部问题"):
            self.answer(ident, "submit")
        with self.assertRaisesRegex(ValueError, "请选择"):
            self.answer(ident, "answer", question_id="size", value="invalid")
        self.answer(ident, "answer", question_id="size", value="上屏")
        self.assertEqual(self.codex.snapshot()["question"]["focus"], "style")
        self.answer(ident, "answer", question_id="style", value="像素风")
        self.answer(ident, "submit")
        self.answer(ident, "submit")
        self.assertEqual(self.rpc.replies, [("server-request-7", {"answers": {
            "size": {"answers": ["上屏"]}, "style": {"answers": ["像素风"]}}})])
        self.assertTrue(self.rpc.started.empty())
        self.assertIsNone(self.codex.snapshot()["question"])
        self.assertEqual(self.codex.snapshot()["messages"][-1]["question_request"]["status"], "answered")

    def test_question_survives_switching_and_rejects_cross_chat_answers(self):
        ident = self.ask()
        self.codex.reset()
        with self.assertRaisesRegex(ValueError, "会话或提问"):
            self.answer(ident, "answer", question_id="style", value="wrong session")
        self.codex.select(self.thread, False)
        self.assertEqual(self.codex.snapshot()["question"]["id"], ident)
        following = self.codex.snapshot(include_following=True)["follow_activity"]
        self.assertEqual(following[0]["status"], "waiting")
        self.assertTrue(following[0]["busy"])

    def test_resolved_or_stopped_question_cannot_be_answered(self):
        ident = self.ask()
        self.rpc.notification("serverRequest/resolved", {"threadId": self.thread, "requestId": "server-request-7"})
        with self.assertRaisesRegex(ValueError, "已结束"):
            self.answer(ident, "answer", question_id="style", value="late")
        ident = self.ask()
        self.rpc.notification("turn/completed", {"threadId": self.thread, "turn": {"id": self.turn, "status": "interrupted"}})
        with self.assertRaisesRegex(ValueError, "已结束"):
            self.answer(ident, "submit")
        self.assertEqual(self.rpc.replies, [])

    def test_secret_answers_are_masked_in_snapshots(self):
        ident = self.ask([{"id": "secret", "question": "输入测试口令", "header": "口令", "isSecret": True}])
        self.answer(ident, "answer", question_id="secret", value="private-test-value")
        self.assertNotIn("private-test-value", str(self.codex.snapshot()))
        self.answer(ident, "submit")
        self.assertEqual(self.rpc.replies[0][1]["answers"]["secret"]["answers"], ["private-test-value"])
        self.assertNotIn("private-test-value", str(self.codex.snapshot()))

    def test_display_question_answer_starts_one_followup_turn(self):
        self.rpc.notification("item/completed", {"threadId": self.thread, "turnId": self.turn, "item": {
            "type": "agentMessage", "id": "async-question", "text": "请确认", "questions": [
                {"title": "选择主题", "options": ["黄色", "深色"]}]}})
        self.rpc.notification("turn/completed", {"threadId": self.thread, "turn": {"id": self.turn, "status": "completed"}})
        ident = self.codex.snapshot()["question"]["id"]
        self.answer(ident, "answer", question_id="0", value="黄色")
        self.answer(ident, "submit")
        self.rpc.started.get(timeout=2)
        self.answer(ident, "submit")
        self.assertTrue(self.rpc.started.empty())
        self.assertEqual(self.codex.snapshot()["messages"][-1]["text"], "选择主题\n黄色")

    def test_cancel_returns_empty_protocol_answers(self):
        ident = self.ask()
        self.answer(ident, "cancel")
        self.assertEqual(self.rpc.replies, [("server-request-7", {"answers": {}})])
        self.assertIsNone(self.codex.snapshot()["question"])
