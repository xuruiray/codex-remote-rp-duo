"""Keep a question's answers scoped to the originating conversation and request."""

import uuid
from dataclasses import dataclass, field


@dataclass
class QuestionSet:
    item_id: str
    turn_id: str | None
    questions: list
    rpc_id: str | int | None = None
    blocking: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "pending"
    answers: dict = field(default_factory=dict)
    focus: str = ""

    def __post_init__(self):
        normalized = []
        for index, source in enumerate(self.questions):
            ident = source.get("id", str(index))
            title = source.get("question", source.get("title"))
            if not isinstance(ident, str) or not isinstance(title, str) or not title.strip():
                raise ValueError("提问内容无效")
            options = []
            for option in source.get("options") or []:
                if isinstance(option, str):
                    option = {"label": option, "description": ""}
                if not isinstance(option, dict) or not isinstance(option.get("label"), str):
                    raise ValueError("提问选项无效")
                options.append({"label": option["label"], "description": option.get("description", "")})
            normalized.append({"id": ident, "title": title, "header": source.get("header", ""),
                               "options": options, "secret": source.get("isSecret") is True,
                               "other": not options or self.rpc_id is None or source.get("isOther") is True})
        if not normalized or len({q["id"] for q in normalized}) != len(normalized):
            raise ValueError("提问编号无效")
        self.questions = normalized
        self.focus = normalized[0]["id"]

    def question(self, ident):
        return next((q for q in self.questions if q["id"] == ident), None)

    def answer(self, ident, value):
        question = self.question(ident)
        if question is None or not isinstance(value, str) or not value.strip() or len(value) > 8000:
            raise ValueError("请输入有效回答")
        if not question["other"] and value not in [option["label"] for option in question["options"]]:
            raise ValueError("请选择上屏列出的选项")
        self.answers[ident] = value.strip()
        self.focus = next((q["id"] for q in self.questions if q["id"] not in self.answers), ident)

    @property
    def ready(self):
        return all(q["id"] in self.answers for q in self.questions)

    def public(self):
        return {"id": self.id, "item_id": self.item_id, "status": self.status,
                "kind": "request" if self.rpc_id is not None else "message",
                "blocking": self.blocking, "questions": self.questions, "focus": self.focus,
                "answers": {q["id"]: "已填写保密回答" if q["secret"] else self.answers[q["id"]]
                            for q in self.questions if q["id"] in self.answers}, "ready": self.ready}

    def response(self):
        if not self.ready:
            raise ValueError("请先回答全部问题")
        return {"answers": {ident: {"answers": [answer]} for ident, answer in self.answers.items()}}

    def message(self):
        return "\n\n".join(q["title"] + "\n" + self.answers[q["id"]] for q in self.questions)
