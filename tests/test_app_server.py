"""Regression tests for the bridge's subprocess protocol."""

import tempfile
import threading
import unittest
from pathlib import Path

from app_server import AppServer

FAKE_SERVER = """#!/usr/bin/env python3
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "exit-before-response":
        break
    if request["method"] == "notify-and-reply":
        print(json.dumps({"method": "malformed", "params": {}}), flush=True)
    result = json.dumps({"id": request["id"], "result": {"method": request["method"]}})
    print(result, flush=True)
    print(result, flush=True)
"""


class AppServerTests(unittest.TestCase):
    def start_server(self, notification):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        binary = path / "fake-codex"
        binary.write_text(FAKE_SERVER)
        binary.chmod(0o700)
        disconnected = threading.Event()
        server = AppServer(str(binary), path, notification, disconnected.set)
        self.addCleanup(server.close)
        return server, disconnected

    def test_malformed_notification_and_duplicate_reply_leave_transport_usable(self):
        def notification(method, params):
            if method == "malformed":
                raise KeyError("missing item")

        server, _ = self.start_server(notification)
        with self.assertLogs(level="WARNING"):
            self.assertEqual(server.call("notify-and-reply", {}), {"method": "notify-and-reply"})
        self.assertEqual(server.call("second-call", {}), {"method": "second-call"})
        self.assertTrue(server.connected)

    def test_eof_wakes_waiting_call_and_marks_transport_disconnected(self):
        server, disconnected = self.start_server(lambda *_: None)
        with self.assertRaisesRegex(RuntimeError, "Codex 进程已退出"):
            server.call("exit-before-response", {})
        self.assertTrue(disconnected.wait(timeout=2))
        self.assertFalse(server.connected)


if __name__ == "__main__":
    unittest.main()
