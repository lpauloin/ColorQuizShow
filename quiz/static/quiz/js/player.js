// Player phone UI. Choices are still color-coded, but labels use the player's language.
(function () {
  const app = document.getElementById("player-app");
  const playerId = app.dataset.playerId;
  const questionBox = document.getElementById("player-question");
  const messageBox = document.getElementById("player-message");
  const languageToggle = document.getElementById("language-toggle");
  const buttons = Array.from(document.querySelectorAll(".choice"));
  const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws/player/${playerId}/`);

  let canAnswer = false;
  let currentState = null;
  let language = app.dataset.language || "fr";

  const labels = {
    fr: {
      answerNow: "Vous pouvez répondre",
      averageTime: "Temps moyen",
      correctAnswer: "Bonne réponse",
      finished: "Quiz terminé",
      invalid: "Réponse refusée",
      noTime: "-",
      prepare: "Préparez-vous",
      question: "Question",
      rank: "Classement",
      result: "Résultat",
      score: "Score",
      sent: "En attente du résultat",
      tooLate: "Trop tard",
      waiting: "En attente",
      yourAnswer: "Votre réponse",
      medals: {
        gold: "Coupe en or",
        silver: "Coupe en argent",
        bronze: "Coupe en bronze",
      },
    },
    vi: {
      answerNow: "Bạn có thể trả lời",
      averageTime: "Thời gian trung bình",
      correctAnswer: "Đáp án đúng",
      finished: "Trò chơi đã kết thúc",
      invalid: "Câu trả lời bị từ chối",
      noTime: "-",
      prepare: "Hãy chuẩn bị",
      question: "Câu hỏi",
      rank: "Xếp hạng",
      result: "Kết quả",
      score: "Điểm",
      sent: "Đang chờ kết quả",
      tooLate: "Quá muộn rồi",
      waiting: "Đang chờ",
      yourAnswer: "Câu trả lời của bạn",
      medals: {
        gold: "Cúp vàng",
        silver: "Cúp bạc",
        bronze: "Cúp đồng",
      },
    },
  };

  function t(key) {
    return labels[language][key];
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[c]));
  }

  function setButtons(enabled) {
    canAnswer = enabled;
    buttons.forEach(button => button.disabled = !enabled);
  }

  function send(payload) {
    if (socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  }

  function answerText(answer) {
    if (!answer) return "...";
    return language === "vi" ? answer.text_vi : answer.text_fr;
  }

  function questionText(question) {
    if (!question) return "";
    return language === "vi" ? question.text_vi : question.text_fr;
  }

  function findAnswer(question, color) {
    if (!question) return null;
    return question.colors.find(answer => answer.color === color);
  }

  function setChoiceLabels(question) {
    buttons.forEach(button => {
      const answer = findAnswer(question, button.dataset.color);
      button.innerHTML = answer ? `<span>${escapeHtml(answerText(answer))}</span>` : "";
    });
  }

  function updateLanguageToggle() {
    languageToggle.textContent = language === "vi" ? "🇻🇳" : "🇫🇷";
    languageToggle.title = language === "vi" ? "Tiếng Việt" : "Français";
  }

  function formatTime(ms, answeredCount) {
    if (!answeredCount) return t("noTime");
    return `${(ms / 1000).toFixed(1)}s`;
  }

  function trophyHtml(result) {
    const medal = result && result.medal;
    if (!medal || !medal.type) return "";
    return `
      <div class="player-trophy ${medal.type}">🏆</div>
      <div class="player-medal-label">${escapeHtml(labels[language].medals[medal.type])}</div>
    `;
  }

  function renderFinished(state) {
    app.classList.add("is-finished");
    setChoiceLabels(null);
    setButtons(false);
    messageBox.textContent = t("finished");

    const result = state.player && state.player.result;
    if (!result) {
      questionBox.innerHTML = `<div class="player-final"><h1>${escapeHtml(t("finished"))}</h1></div>`;
      return;
    }

    questionBox.innerHTML = `
      <div class="player-final">
        ${trophyHtml(result)}
        <h1>${escapeHtml(t("finished"))}</h1>
        <div class="player-stat">
          <span>${escapeHtml(t("score"))}</span>
          <strong>${result.correct_count} / ${state.question_count}</strong>
        </div>
        <div class="player-stat">
          <span>${escapeHtml(t("averageTime"))}</span>
          <strong>${formatTime(result.avg_reaction_time_ms, result.answered_count)}</strong>
        </div>
        <div class="player-stat">
          <span>${escapeHtml(t("rank"))}</span>
          <strong>#${result.rank}</strong>
        </div>
      </div>
    `;
  }

  function renderResult(state) {
    const q = state.question;
    const correctAnswer = findAnswer(q, q.correct_color);
    const playerAnswer = state.player && state.player.current_answer
      ? findAnswer(q, state.player.current_answer.color)
      : null;

    setButtons(false);
    messageBox.textContent = t("result");
    questionBox.innerHTML = `
      <div>
        <div class="answer-summary-label">${escapeHtml(t("correctAnswer"))}</div>
        <div class="answer-summary-text">${escapeHtml(answerText(correctAnswer))}</div>
        ${playerAnswer ? `
          <div class="answer-summary-label">${escapeHtml(t("yourAnswer"))}</div>
          <div class="answer-summary-text">${escapeHtml(answerText(playerAnswer))}</div>
        ` : ""}
      </div>
    `;
  }

  function renderState(state) {
    currentState = state;
    if (state.player && state.player.language) language = state.player.language;
    updateLanguageToggle();

    if (state.quiz.status === "finished") {
      renderFinished(state);
      return;
    }

    app.classList.remove("is-finished");
    const q = state.question;
    setChoiceLabels(state.phase === "answering" ? q : null);

    if (!q) {
      setButtons(false);
      questionBox.innerHTML = `<div>${escapeHtml(t("waiting"))}</div>`;
      messageBox.textContent = t("waiting");
      return;
    }

    if (state.phase === "answering") {
      const alreadyAnswered = Boolean(state.player && state.player.has_answered_current_question);
      setButtons(!alreadyAnswered);
      messageBox.textContent = alreadyAnswered ? t("sent") : t("answerNow");
      questionBox.innerHTML = `
        <div>
          <div>${escapeHtml(t("question"))} ${state.question_index} / ${state.question_count}</div>
          <br>
          <div>${escapeHtml(questionText(q))}</div>
        </div>
      `;
      return;
    }

    if (state.phase === "result") {
      renderResult(state);
      return;
    }

    setButtons(false);
    messageBox.textContent = t("prepare");
    questionBox.innerHTML = `<div>${escapeHtml(t("prepare"))}</div>`;
  }

  buttons.forEach(button => {
    button.onclick = () => {
      if (!canAnswer) return;
      setButtons(false);
      send({ action: "answer", color: button.dataset.color });
      messageBox.textContent = t("sent");
    };
  });

  languageToggle.onclick = () => {
    language = language === "vi" ? "fr" : "vi";
    updateLanguageToggle();
    if (currentState && currentState.player) {
      currentState.player.language = language;
      renderState(currentState);
    }
    send({ action: "set_language", language });
  };

  updateLanguageToggle();
  setChoiceLabels(null);
  setButtons(false);

  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === "state") renderState(message.state);
    if (message.type === "answer_rejected") {
      setButtons(false);
      messageBox.textContent = message.reason === "invalid_color" ? t("invalid") : t("tooLate");
    }
    if (message.type === "answer_saved") {
      messageBox.textContent = t("sent");
    }
    if (message.type === "language_rejected") {
      messageBox.textContent = t("invalid");
    }
  };
})();
