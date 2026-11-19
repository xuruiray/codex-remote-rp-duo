/** Question actions stay scoped to their originating thread, even across selection changes. */
export function mountQuestions({request, refresh, showError, editSecret}) {
  let thread = null;
  let busy = false;
  let sending = false;

  async function act(question, action, data = {}) {
    if (sending) return;
    const selected = thread;
    sending = true;
    try {
      await request("question", {thread_id: selected, request_id: question.id, action, ...data});
      if (thread === selected) await refresh();
    } catch (failure) {
      if (thread === selected) showError(failure.message);
    } finally {
      sending = false;
    }
  }

  function button(label, action) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "subtle";
    node.textContent = label;
    node.addEventListener("click", action);
    return node;
  }

  function render(entry, source) {
    const request = entry.question_request;
    const active = request?.status === "pending";
    const cards = document.createElement("div");
    cards.className = "question-cards";
    if (request) cards.dataset.questionRequest = request.id;
    cards.setAttribute("aria-label", "Codex 的提问");
    const questions = request?.questions || source.map((q, index) => ({...q, id: String(index)}));
    for (const question of questions) {
      const card = document.createElement("section");
      card.className = "question-card";
      card.dataset.questionId = question.id;
      if (active && request.focus === question.id) card.classList.add("is-current");
      const title = document.createElement("p");
      title.className = "question-title";
      title.textContent = question.title;
      card.append(title);
      if (question.options?.length) {
        const options = document.createElement("div");
        options.className = "question-options";
        for (const option of question.options) {
          const label = typeof option === "string" ? option : option.label;
          const choice = button(label, () => act(request, "answer", {question_id: question.id, value: label}));
          choice.disabled = !active;
          choice.setAttribute("aria-pressed", String(request?.answers[question.id] === label));
          if (option.description) {
            const description = document.createElement("small");
            description.textContent = option.description;
            choice.append(description);
          }
          options.append(choice);
        }
        card.append(options);
      }
      if (active && (question.other || question.secret)) {
        const edit = button(question.secret ? "填写保密回答" : "用下屏回答", () => {
          if (question.secret) {
            if (editSecret(request, question)) return;
            const input = document.createElement("input");
            input.type = "password";
            input.autocomplete = "off";
            input.maxLength = 8000;
            input.setAttribute("aria-label", question.title);
            edit.replaceWith(input, button("保存回答", () => act(request, "answer", {question_id: question.id, value: input.value})));
            input.focus();
          }
          else act(request, "focus", {question_id: question.id});
        });
        edit.classList.add("question-edit");
        card.append(edit);
      }
      if (request?.answers[question.id]) {
        const answer = document.createElement("p");
        answer.className = "question-answer";
        answer.textContent = "回答：" + request.answers[question.id];
        card.append(answer);
      }
      cards.append(card);
    }
    if (request) {
      const footer = document.createElement("div");
      footer.className = "question-actions";
      if (active) {
        const submit = button("提交回答", () => act(request, "submit"));
        submit.disabled = !request.ready || (busy && request.kind === "message");
        submit.classList.remove("subtle");
        footer.append(submit, button("暂不回答", () => act(request, "cancel")));
      } else {
        footer.textContent = {answered: "回答已提交", submitting: "正在提交回答…", dismissed: "已跳过回答", expired: "这条提问已结束"}[request.status] || "历史提问";
      }
      cards.append(footer);
    }
    return cards;
  }

  return {render, update: state => {thread = state.thread_id; busy = state.busy;},
          answerSecret: (question, ident, value) => act(question, "answer", {question_id: ident, value})};
}
