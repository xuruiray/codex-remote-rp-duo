"""History paging must preserve chronology and allow session changes during IO."""

import threading
import unittest
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from codex_session import Chat, Codex


def entry(ident):
    return {"id": ident, "role": "assistant", "text": ident, "complete": True}


def page(items, cursor=None):
    return {"data": [{"id": "turn", "items": [
        {"id": ident, "type": "agentMessage", "text": ident} for ident in items
    ]}], "nextCursor": cursor}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.codex = Codex.__new__(Codex)
        self.codex.lock = threading.RLock()
        self.codex.action = threading.Lock()
        self.codex.workspace = Path.cwd()
        self.codex.session_file = None
        self.chat = Chat(Path.cwd(), id="history", messages=[entry("current")], history_cursor="page-1")
        self.codex.selected = self.chat
        self.codex.chats = OrderedDict([(self.chat.id, self.chat)])
        self.codex._rpc = Mock()

    def test_remote_history_deduplicates_and_keeps_oldest_to_newest_order(self):
        self.codex._rpc.call.side_effect = [page(["older", "current"], "page-2"), page(["oldest", "older"])]
        result = self.codex.older_history("current", "history")
        self.assertEqual([item["id"] for item in result["messages"]], ["oldest", "older"])
        self.assertIsNone(result["history_before"])
        self.assertEqual([item["id"] for item in self.chat.messages], ["oldest", "older", "current"])

    def test_failed_page_can_be_retried_without_losing_history(self):
        self.codex._rpc.call.side_effect = [RuntimeError("temporary error"), page(["older"])]
        with self.assertRaisesRegex(RuntimeError, "temporary"):
            self.codex.older_history("current", "history")
        self.assertEqual(self.chat.history_cursor, "page-1")
        self.assertEqual([item["id"] for item in self.chat.messages], ["current"])
        self.assertEqual(self.codex.older_history("current", "history")["messages"][0]["id"], "older")

    def test_slow_history_fetch_does_not_block_switching_to_new_chat(self):
        started, release = threading.Event(), threading.Event()
        def delayed(*_):
            started.set()
            if not release.wait(timeout=2):
                raise RuntimeError("test deadline")
            return page(["older"])
        self.codex._rpc.call.side_effect = delayed
        with ThreadPoolExecutor(max_workers=2) as pool:
            history = pool.submit(self.codex.older_history, "current", "history")
            self.assertTrue(started.wait(timeout=1))
            selection = pool.submit(self.codex.reset)
            try:
                selection.result(timeout=.5)
                self.assertIsNone(self.codex.selected.id)
            finally:
                release.set()
            with self.assertRaisesRegex(ValueError, "会话已切换"):
                history.result(timeout=1)
        self.assertEqual([item["id"] for item in self.chat.messages], ["current"])

    def test_pagination_cycle_stops_with_a_retryable_error(self):
        self.codex._rpc.call.side_effect = [page([], "page-2"), page([], "page-1")]
        with self.assertRaisesRegex(RuntimeError, "分页位置"):
            self.codex.older_history("current", "history")
        self.assertEqual(self.codex._rpc.call.call_count, 2)


if __name__ == "__main__":
    unittest.main()
