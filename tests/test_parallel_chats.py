import itertools
import tempfile
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from codex_session import Codex


class FakeAppServer:
    connected = True

    def __init__(self, _executable, _workspace, notification, _disconnect, on_request=None):
        self.notification = notification
        self.ids = itertools.count(1)
        self.started = Queue()
        self.interrupts = []
        self.request = on_request
        self.replies = []

    def reply(self, ident, result):
        self.replies.append((ident, result))

    def notify(self, _method):
        pass

    def call(self, method, params):
        if method == "initialize":
            return {}
        if method == "model/list":
            return {"data": [{
                "model": "sample", "displayName": "Sample", "defaultReasoningEffort": "high",
                "supportedReasoningEfforts": [], "isDefault": True,
            }]}
        if method == "thread/start":
            return {"thread": {"id": f"chat-{next(self.ids)}"}}
        if method == "turn/start":
            thread = params["threadId"]
            turn = f"turn-{thread}"
            self.notification("turn/started", {"threadId": thread, "turn": {"id": turn}})
            self.started.put((thread, turn))
            return {}
        if method == "turn/interrupt":
            self.interrupts.append((params["threadId"], params["turnId"]))
            return {}
        raise AssertionError(method)


class ParallelChatsTest(unittest.TestCase):
    def setUp(self):
        workspace = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch("codex_session.AppServer", FakeAppServer))
        self.codex = Codex(Path(workspace), "fake")
        self.rpc = self.codex._rpc

    def start(self, label, expected_thread=None):
        self.codex.start_prompt(label, submission=label, expected_thread=expected_thread)
        return self.rpc.started.get(timeout=2)

    def test_separate_turns_keep_streaming_when_switching_and_stop_is_scoped(self):
        first, first_turn = self.start("first")
        with self.assertRaisesRegex(ValueError, "当前会话无法接收"):
            self.start("overlap in same chat", expected_thread=first)
        self.codex.reset()
        second, second_turn = self.start("second")
        self.assertEqual(set(self.codex.snapshot()["running_thread_ids"]), {first, second})

        self.rpc.notification("item/agentMessage/delta", {
            "threadId": first, "turnId": first_turn, "itemId": "answer", "delta": "first reply",
        })
        self.rpc.notification("item/agentMessage/delta", {
            "threadId": second, "turnId": second_turn, "itemId": "answer", "delta": "second reply",
        })
        self.assertEqual([row["text"] for row in self.codex.snapshot()["messages"]], ["second", "second reply"])
        with self.assertRaisesRegex(ValueError, "会话已切换"):
            self.codex.interrupt(first, first_turn)
        with self.assertRaisesRegex(ValueError, "任务已结束或切换"):
            self.codex.interrupt(second, first_turn)
        self.codex.interrupt(second, second_turn)
        self.assertEqual(self.rpc.interrupts, [(second, second_turn)])

        self.rpc.notification("turn/completed", {
            "threadId": second, "turn": {"id": second_turn, "status": "interrupted"},
        })
        self.codex.select(first, False)
        state = self.codex.snapshot()
        self.assertTrue(state["busy"])
        self.assertEqual(state["turn_id"], first_turn)
        self.assertEqual(state["running_thread_ids"], [first])
        self.assertEqual([row["text"] for row in state["messages"]], ["first", "first reply"])
        self.assertEqual(state["submissions"]["first"]["thread_id"], first)
        self.assertEqual(state["submissions"]["second"]["thread_id"], second)


    def test_sidebar_tracks_background_outcomes_until_viewed(self):
        first, first_turn = self.start("first")
        self.codex.reset()
        second, second_turn = self.start("second")

        def following():
            state = self.codex.snapshot(include_controls=False, include_following=True)
            return {item["id"]: item for item in state["follow_activity"]}

        self.assertEqual({key: row["status"] for key, row in following().items()},
                         {first: "running", second: "running"})
        self.assertNotIn("follow_activity", self.codex.snapshot())
        self.rpc.notification("turn/completed", {
            "threadId": first, "turn": {"id": first_turn, "status": "completed"},
        })
        self.assertTrue(following()[first]["unread"])
        self.assertTrue(following()[first]["follow"])
        self.rpc.notification("turn/completed", {
            "threadId": second, "turn": {"id": second_turn, "status": "failed"},
        })
        self.assertFalse(following()[second]["unread"])
        self.assertEqual(following()[second]["status"], "failed")
        self.codex.select(first, False)
        self.assertFalse(following()[first]["unread"])
        self.assertEqual(following()[first]["status"], "completed")
        self.codex.reset()
        self.assertFalse(following()[first]["follow"])
        self.assertEqual(following()[first]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
