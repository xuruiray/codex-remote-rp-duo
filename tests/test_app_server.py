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

    def test_deferred_question_response_keeps_rpc_reader_available(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(directory)
        binary = path / "fake-codex"
        binary.write_text('''#!/usr/bin/env python3
import json,sys
for line in sys.stdin:
 request=json.loads(line)
 if "method" not in request:
  print(json.dumps({"method":"answered","params":request}),flush=True)
  continue
 if request["method"]=="ask":
  print(json.dumps({"id":"question-7","method":"item/tool/requestUserInput","params":{"question":"pick"}}),flush=True)
 print(json.dumps({"id":request["id"],"result":{}}),flush=True)
''')
        binary.chmod(0o700)
        arrived, answered = threading.Event(), threading.Event()
        received = []
        def on_request(ident, params):
            received.append((ident, params))
            arrived.set()
        def notification(method, params):
            if method == "answered":
                received.append(params)
                answered.set()
        server = AppServer(str(binary), path, notification, lambda: None, on_request)
        self.addCleanup(server.close)
        server.call("ask", {})
        self.assertTrue(arrived.wait(1))
        self.assertEqual(received[0], ("question-7", {"question": "pick"}))
        self.assertEqual(server.call("ping-while-waiting", {}), {})
        server.reply("question-7", {"answers": {"size": {"answers": ["upper"]}}})
        self.assertTrue(answered.wait(1))
        self.assertEqual(received[1], {"id": "question-7", "result": {"answers": {"size": {"answers": ["upper"]}}}})


if __name__ == "__main__":
    unittest.main()
