"""Cold loads may finish late; only the newest selection is allowed to commit."""

import threading
import unittest
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

from codex_session import Chat, Codex


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.codex = Codex.__new__(Codex)
        self.codex.workspace = Path.cwd()
        self.codex.session_file = None
        self.codex.lock = threading.RLock()
        self.codex.action = threading.Lock()
        self.codex.selection_request = 0
        self.codex.opening_thread = None
        self.codex.selected = Chat(Path.cwd())
        self.codex.chats = OrderedDict()
        self.codex._rpc = Mock()

    def race(self, delay_method, next_selection):
        started, release = threading.Event(), threading.Event()
        def rpc(method, params):
            if params["threadId"] == "slow" and method == delay_method:
                started.set()
                if not release.wait(2):
                    raise RuntimeError("test deadline")
            return {"thread": {"id": params["threadId"], "cwd": str(Path.cwd()), "name": params["threadId"]}} if method == "thread/read" else {"data": []}
        self.codex._rpc.call.side_effect = rpc
        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(self.codex.select, "slow", False)
            self.assertTrue(started.wait(1))
            try:
                self.assertEqual(self.codex.snapshot(include_controls=False)["opening_thread_id"], "slow")
                new = pool.submit(next_selection)
                new.result(timeout=.5)
                chosen = self.codex.selected
            finally:
                release.set()
            old.result(timeout=1)
        self.assertIs(self.codex.selected, chosen)
        self.assertIsNone(self.codex.opening_thread)

    def test_new_chat_is_immediate_during_metadata_rpc(self):
        self.race("thread/read", self.codex.reset)
        self.assertIsNone(self.codex.selected.id)

    def test_newer_cold_selection_wins_during_initial_history_rpc(self):
        self.race("thread/turns/list", lambda: self.codex.select("fast", False))
        self.assertEqual(self.codex.selected.id, "fast")

    def test_metadata_failure_keeps_current_selection_and_clears_loading(self):
        previous = self.codex.selected
        self.codex._rpc.call.side_effect = RuntimeError("temporary offline")
        with self.assertRaisesRegex(RuntimeError, "temporary offline"):
            self.codex.select("unavailable", False)
        self.assertIs(self.codex.selected, previous)
        self.assertIsNone(self.codex.opening_thread)
