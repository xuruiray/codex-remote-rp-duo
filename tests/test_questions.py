"""Keep desktop question content visible through the bridge's normal history path."""

import unittest
from pathlib import Path

from codex_session import Chat, Codex
from session_messages import export_entry, session_entry


class QuestionHistoryTests(unittest.TestCase):
    def test_agent_question_survives_history_and_export_with_empty_text(self):
        questions = [{"title": "请选择壁纸尺寸", "options": ["1920×1080", "1280×960"]}]
        page = {"data": [{"items": [{"type": "agentMessage", "id": "question", "text": "", "questions": questions}]}]}
        entries = Codex.turn_entries(page)
        self.assertEqual(len(entries), 1)
        self.assertEqual(export_entry(entries[0])["questions"], questions)

    def test_plain_assistant_messages_still_export_without_question_cards(self):
        entry = session_entry({"type": "agentMessage", "id": "plain", "text": "完成", "questions": None})
        self.assertEqual(export_entry(entry)["text"], "完成")
        self.assertFalse(export_entry(entry).get("questions"))

    def test_streamed_question_update_reaches_snapshot_history(self):
        questions = [{"title": "要保留哪些照片？", "options": None}]
        chat = Chat(Path.cwd(), id="thread")
        chat.update_item({"type": "agentMessage", "id": "question", "text": "请确认"}, False)
        chat.update_item({"type": "agentMessage", "id": "question", "text": "请确认", "questions": questions}, True)
        self.assertEqual(chat.history_slice(1)["messages"][0]["questions"], questions)


if __name__ == "__main__":
    unittest.main()
