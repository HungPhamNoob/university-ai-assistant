/* services/frontend/static/js/chat.js
 * Chat area: turn rendering, the Claude-style transparency timeline, SSE
 * stream consumption, HITL (interrupt -> approve/reject -> resume), stop,
 * and auto-scroll with user-override. */

window.UET = window.UET || {};

(function () {
  "use strict";

  var ui = window.UET.ui;
  var markdown = window.UET.markdown;

  var AGENT_LABELS = {
    faq_agent: "FAQ — Chính sách nội bộ",
    search_agent: "Web Search — Thông tin thời sự",
    booking_agent: "Booking — Đặt phòng họp",
    general_chat: "Trò chuyện chung",
  };

  var TOOL_LABELS = {
    search_uet_knowledge: "Tra cứu tri thức UET",
    search_web: "Tìm kiếm web",
    book_meeting_room: "Đặt phòng họp",
    list_my_bookings: "Xem phòng đã đặt",
    cancel_booking: "Hủy đặt phòng",
  };

  var TITLES_KEY = "uet.titles";

  var state = {
    threadId: null,
    controller: null,
    streaming: false,
    activeTurn: null,
    userScrolledUp: false,
    threadFilled: false, // true once the current thread already has turns
  };

  var els = {};

  // ---- tiny helpers ----

  function randomId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return c === "x" ? r.toString(16) : ((r & 0x3) | 0x8).toString(16);
    });
  }

  function readTitles() {
    try {
      return JSON.parse(localStorage.getItem(TITLES_KEY)) || {};
    } catch (err) {
      return {};
    }
  }

  function rememberTitle(threadId, text) {
    var titles = readTitles();
    titles[threadId] = String(text || "").replace(/\s+/g, " ").slice(0, 60);
    try {
      localStorage.setItem(TITLES_KEY, JSON.stringify(titles));
    } catch (err) {
      /* ignore quota errors */
    }
  }

  function currentIdentity() {
    var auth = window.UET.auth;
    return auth.identity() || { user_id: "anonymous", email: null, name: "Khách" };
  }

  // ---- scroll ----

  function onScroll() {
    var nearBottom =
      els.chatScroll.scrollHeight - els.chatScroll.scrollTop - els.chatScroll.clientHeight < 60;
    state.userScrolledUp = !nearBottom;
    els.scrollDownBtn.classList.toggle("hidden", nearBottom);
  }

  function scrollToBottom(force) {
    if (force || !state.userScrolledUp) {
      els.chatScroll.scrollTop = els.chatScroll.scrollHeight;
    }
  }

  function resumeAutoScroll() {
    state.userScrolledUp = false;
    scrollToBottom(true);
  }

  // ---- header / busy ----

  function setHeaderStatus(text) {
    els.headerStatus.textContent = text || "";
  }

  function setStreaming(on) {
    state.streaming = on;
    els.sendBtn.classList.toggle("hidden", on);
    els.stopBtn.classList.toggle("hidden", !on);
    els.chatInput.disabled = false;
  }

  function hideEmptyState() {
    els.emptyState.classList.add("hidden");
  }
  function showEmptyState() {
    els.emptyState.classList.remove("hidden");
  }

  // ---- turn construction ----

  function createTurn(userText) {
    var turn = {
      userText: userText,
      raw: "",
      raf: 0,
      agentName: null,
      agentLabel: null,
      toolChips: {}, // name -> array of {el, done}
      toolCount: 0,
      pendingInterrupt: null,
      streamError: null,
      status: "streaming",
      startedAt: Date.now(), // drives the live elapsed counter
      timer: 0,
    };

    var wrap = ui.el("section", "turn turn-active");
    var userRow = ui.el("div", "user-row");
    var bubble = ui.el("div", "bubble user");
    bubble.textContent = userText;
    userRow.appendChild(bubble);
    wrap.appendChild(userRow);

    var assist = ui.el("div", "assist");

    // Collapsible transparency timeline.
    var details = ui.el("details", "timeline");
    details.open = true;
    var summary = ui.el("summary", "timeline-summary");
    var summaryMeta = ui.el("span", "ts-meta");
    summary.appendChild(ui.el("span", "ts-label", "Đang xử lý…"));
    summary.appendChild(summaryMeta);
    details.appendChild(summary);

    var body = ui.el("div", "timeline-body");
    var badge = ui.el("div", "agent-badge hidden");
    badge.appendChild(
      (function () {
        var span = ui.el("span", "agent-badge-icon");
        span.innerHTML = ui.svg("spark", "icon");
        return span;
      })()
    );
    badge.appendChild(ui.el("span", "agent-badge-label"));
    var toolRow = ui.el("div", "tool-row");
    // Ordered activity log: every router switch / tool call lands here so the
    // user can see *what* the assistant is doing, not just that it is busy.
    var activityFeed = ui.el("ol", "activity-feed");
    body.appendChild(badge);
    body.appendChild(toolRow);
    body.appendChild(activityFeed);
    details.appendChild(body);
    assist.appendChild(details);

    // Answer container.
    var answerWrap = ui.el("div", "turn-answer");
    var answerBody = ui.el("div", "markdown-body answer-body");
    answerBody.innerHTML = '<span class="thinking">Đang suy nghĩ<span class="dots" aria-hidden="true"></span></span>';
    answerWrap.appendChild(answerBody);
    assist.appendChild(answerWrap);

    // Extra host: HITL card / error / stopped notes.
    var extraHost = ui.el("div", "turn-extra");
    assist.appendChild(extraHost);

    wrap.appendChild(assist);

    turn.wrap = wrap;
    turn.details = details;
    turn.summaryMeta = summaryMeta;
    turn.summaryLabel = summary.querySelector(".ts-label");
    turn.badge = badge;
    turn.badgeLabel = badge.querySelector(".agent-badge-label");
    turn.toolRow = toolRow;
    turn.activityEl = activityFeed;
    turn.answerBody = answerBody;
    turn.extraHost = extraHost;

    els.chatLog.appendChild(wrap);
    startTurnTimer(turn);
    return turn;
  }

  // ---- activity timeline ----

  function elapsedLabel(turn) {
    if (!turn.startedAt) {
      return ""; // static (restored) turns have no timing
    }
    var seconds = (Date.now() - turn.startedAt) / 1000;
    return (seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)) + "s";
  }

  function liveMeta(turn) {
    var tools = turn.toolCount ? turn.toolCount + " công cụ · " : "";
    return tools + elapsedLabel(turn);
  }

  /* Ticks the "Đang xử lý… · N công cụ · 3.1s" summary while a turn streams. */
  function startTurnTimer(turn) {
    stopTurnTimer(turn);
    turn.timer = window.setInterval(function () {
      if (turn.status !== "streaming") {
        stopTurnTimer(turn);
        return;
      }
      turn.summaryMeta.textContent = liveMeta(turn);
    }, 500);
  }

  function stopTurnTimer(turn) {
    if (turn.timer) {
      window.clearInterval(turn.timer);
      turn.timer = 0;
    }
  }

  /* The live accent marks the one turn that is streaming right now. Every
     terminal path (done / paused / stopped / error / cleared) switches it off
     and a HITL resume switches it back on, so finished turns never look busy. */
  function setTurnLive(turn, live) {
    if (!turn || !turn.wrap) {
      return;
    }
    turn.wrap.classList.toggle("turn-active", !!live);
  }

  /* Append one ordered step to the transparency timeline. */
  function logActivity(turn, kind, text) {
    if (!turn.activityEl) {
      return;
    }
    var item = ui.el("li", "activity-item activity-" + kind);
    item.appendChild(ui.el("span", "activity-dot"));
    item.appendChild(ui.el("span", "activity-text", text));
    item.appendChild(ui.el("span", "activity-time", elapsedLabel(turn)));
    turn.activityEl.appendChild(item);
    scrollToBottom(false);
  }

  function setAgent(turn, data) {
    if (!data || !data.name) {
      return;
    }
    var previous = turn.agentName;
    turn.agentName = data.name;
    turn.agentLabel = data.label || AGENT_LABELS[data.name] || data.name;
    turn.badgeLabel.textContent = turn.agentLabel;
    turn.badge.classList.remove("hidden");
    turn.badge.classList.add("is-active");
    if (previous !== data.name) {
      logActivity(
        turn,
        "agent",
        previous ? "Chuyển sang " + turn.agentLabel : "Định tuyến → " + turn.agentLabel
      );
    }
    setHeaderStatus("Đang trả lời: " + turn.agentLabel);
  }

  function onTool(turn, data) {
    var toolName = data && data.name ? data.name : "tool";
    var status = data && data.status ? data.status : "start";
    var label = TOOL_LABELS[toolName] || toolName;
    if (status !== "end") {
      var chip = ui.el("span", "tool-chip");
      chip.title = toolName;
      var spinIcon = ui.el("span", "tool-spin");
      spinIcon.innerHTML = ui.svg("spark", "icon");
      var nameEl = ui.el("span", "tool-name", label);
      var timeEl = ui.el("span", "tool-time", "");
      chip.appendChild(spinIcon);
      chip.appendChild(nameEl);
      chip.appendChild(timeEl);
      turn.toolRow.appendChild(chip);
      turn.toolChips[toolName] = turn.toolChips[toolName] || [];
      turn.toolChips[toolName].push({ el: chip, timeEl: timeEl, done: false, startedAt: Date.now() });
      turn.toolCount += 1;
      logActivity(turn, "tool", "Đang gọi " + label);
      setHeaderStatus("Đang dùng công cụ: " + label);
    } else {
      var list = turn.toolChips[toolName] || [];
      for (var i = list.length - 1; i >= 0; i -= 1) {
        if (!list[i].done) {
          list[i].done = true;
          var spin = list[i].el.querySelector(".tool-spin");
          if (spin) {
            spin.innerHTML = ui.svg("check", "icon");
            spin.classList.add("is-done");
          }
          list[i].el.classList.add("is-done");
          var seconds = (Date.now() - (list[i].startedAt || turn.startedAt)) / 1000;
          if (list[i].timeEl) {
            list[i].timeEl.textContent = (seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)) + "s";
          }
          logActivity(turn, "tool-done", label + " hoàn tất (" + seconds.toFixed(1) + "s)");
          break;
        }
      }
      setHeaderStatus(
        turn.agentLabel ? "Đang trả lời: " + turn.agentLabel : "Đang xử lý…"
      );
    }
  }

  function onToken(turn, text) {
    turn.raw += text;
    scheduleRender(turn);
  }

  /* Context-engineering transparency: what the agent's context assembly did
     this turn (memory injection, history trimming, oversized tool outputs,
     system-prompt budget). Arrives once per turn, right before 'done'. */
  function onContext(turn, data) {
    if (!data) {
      return;
    }
    if (data.memory_injected) {
      logActivity(turn, "context", "Đã nạp ký ức cuộc trò chuyện (bản tóm tắt, dữ liệu không tin cậy)");
    }
    if (data.history_trimmed) {
      logActivity(
        turn,
        "context",
        "Lịch sử dài — chỉ giữ " + data.history_messages_out + "/" +
          data.history_messages_in + " tin nhắn gần nhất cho vừa budget"
      );
    }
    if (data.tool_outputs_capped > 0) {
      logActivity(
        turn,
        "context",
        "Đã cắt gọn " + data.tool_outputs_capped + " kết quả công cụ quá khổ"
      );
    }
    if (data.system_over_budget) {
      logActivity(turn, "context", "System prompt vượt token budget — giữ nguyên (cảnh báo cấu hình)");
    }
  }

  function scheduleRender(turn) {
    if (turn.raf) {
      return;
    }
    turn.raf = window.requestAnimationFrame(function () {
      turn.raf = 0;
      renderAnswer(turn);
      scrollToBottom(false);
    });
  }

  function renderAnswer(turn) {
    if (turn.raw.length === 0) {
      turn.answerBody.innerHTML =
        '<span class="thinking">Đang suy nghĩ<span class="dots" aria-hidden="true"></span></span>';
      return;
    }
    turn.answerBody.innerHTML = markdown.render(turn.raw);
  }

  function completeTurn(turn) {
    turn.badge.classList.remove("is-active");
    if (!turn.raw.length) {
      turn.answerBody.innerHTML = '<p class="muted">Không có nội dung trả lời.</p>';
    } else {
      renderAnswer(turn);
    }
    stopTurnTimer(turn);
    setTurnLive(turn, false);
    turn.status = "done";
    turn.details.open = false;
    var label = turn.agentLabel || "Trợ lý";
    turn.summaryLabel.textContent = label;
    turn.summaryMeta.textContent = (turn.toolCount > 0 ? turn.toolCount + " công cụ · " : "") +
      elapsedLabel(turn);
    turn.details.classList.add("is-done");
    logActivity(turn, "done", "Hoàn thành sau " + elapsedLabel(turn));
    setHeaderStatus("");
  }

  function setPaused(turn) {
    stopTurnTimer(turn);
    setTurnLive(turn, false);
    turn.status = "paused";
    turn.summaryLabel.textContent = "Chờ xác nhận";
    turn.summaryMeta.textContent = elapsedLabel(turn);
    logActivity(turn, "pause", "Chờ bạn xác nhận đặt phòng");
    setHeaderStatus("Chờ bạn xác nhận");
    scrollToBottom(true);
  }

  function markStopped(turn) {
    stopTurnTimer(turn);
    setTurnLive(turn, false);
    turn.status = "stopped";
    turn.details.open = false;
    var label = turn.agentLabel || "Trợ lý";
    turn.summaryLabel.textContent = label;
    turn.summaryMeta.textContent = "đã dừng · " + elapsedLabel(turn);
    logActivity(turn, "stopped", "Đã dừng theo yêu cầu");
    appendNote(turn, "Đã dừng.");
    setHeaderStatus("");
  }

  function markError(turn, err) {
    stopTurnTimer(turn);
    setTurnLive(turn, false);
    turn.status = "error";
    turn.details.open = false;
    var label = turn.agentLabel || "Trợ lý";
    turn.summaryLabel.textContent = label;
    turn.summaryMeta.textContent = "lỗi · " + elapsedLabel(turn);
    logActivity(turn, "error", "Gặp lỗi khi xử lý");
    setHeaderStatus("");
    appendError(turn, err);
  }

  function appendNote(turn, text) {
    var note = ui.el("p", "turn-note");
    note.textContent = text;
    turn.extraHost.appendChild(note);
  }

  function appendError(turn, err) {
    var box = ui.el("div", "error-card");
    box.setAttribute("role", "alert");
    var titleEl = ui.el("p", "error-title", "Đã xảy ra lỗi");
    box.appendChild(titleEl);

    var message = err && err.message ? err.message : String(err);
    var friendly =
      message === "AbortError"
        ? "Đã dừng."
        : "Không thể xử lý yêu cầu. Vui lòng thử lại.";
    box.appendChild(ui.el("p", "error-message", friendly));

    var retry = ui.el("button", "btn btn-ghost btn-sm");
    retry.textContent = "Thử lại";
    retry.addEventListener("click", function () {
      els.chatInput.value = turn.userText;
      resizeInput();
      els.chatInput.focus();
    });
    box.appendChild(retry);

    turn.extraHost.appendChild(box);
    scrollToBottom(true);
  }

  // ---- HITL ----

  function hitlDetails(details) {
    var labels = {
      room: "Phòng",
      time: "Thời gian",
      duration_minutes: "Thời lượng",
      purpose: "Mục đích",
      booking_id: "Mã đặt phòng",
      user_id: "Người đặt",
    };
    var rows = [];
    if (!details) {
      return rows;
    }
    Object.keys(details).forEach(function (key) {
      var value = details[key];
      if (value === null || value === undefined || value === "") {
        return;
      }
      var display = key === "duration_minutes" ? value + " phút" : String(value);
      rows.push({ label: labels[key] || key, value: display });
    });
    return rows;
  }

  // Tiêu đề thẻ HITL theo action của interrupt (map thay cho nested ternary —
  // thêm action mới chỉ cần thêm 1 dòng).
  var HITL_TITLES = {
    book_room: "Xác nhận đặt phòng họp",
    cancel_booking: "Xác nhận hủy đặt phòng",
    reschedule_booking: "Xác nhận đổi lịch đặt phòng",
  };

  function renderHitlCard(turn) {
    var interrupt = turn.pendingInterrupt;
    var action = interrupt.action;
    var title = HITL_TITLES[action] || "Yêu cầu xác nhận";

    var card = ui.el("div", "hitl-card");
    var head = ui.el("div", "hitl-head");
    var icon = ui.el("span", "hitl-icon");
    icon.innerHTML = ui.svg("shield", "icon");
    head.appendChild(icon);
    head.appendChild(ui.el("strong", null, title));
    card.appendChild(head);

    if (interrupt.message) {
      card.appendChild(ui.el("p", "hitl-message", interrupt.message));
    }

    var rows = hitlDetails(interrupt.details);
    if (rows.length) {
      var dl = ui.el("div", "hitl-details");
      rows.forEach(function (row) {
        var div = ui.el("div", "hitl-row");
        div.appendChild(ui.el("span", "hitl-key", row.label));
        div.appendChild(ui.el("span", "hitl-value", row.value));
        dl.appendChild(div);
      });
      card.appendChild(dl);
    }

    var actions = ui.el("div", "hitl-actions");
    var approve = ui.el("button", "btn btn-approve");
    approve.textContent = "Đồng ý";
    var reject = ui.el("button", "btn btn-reject");
    reject.textContent = "Hủy";
    actions.appendChild(approve);
    actions.appendChild(reject);
    card.appendChild(actions);

    approve.addEventListener("click", function () {
      resolveHitl(turn, true, actions);
    });
    reject.addEventListener("click", function () {
      resolveHitl(turn, false, actions);
    });

    turn.extraHost.appendChild(card);
    return card;
  }

  function resolveHitl(turn, approved, actionsEl) {
    // Mark the current card resolved and disable its buttons.
    actionsEl.innerHTML = "";
    var status = ui.el("span", "hitl-resolved");
    status.textContent = approved ? "Đã xác nhận" : "Đã từ chối";
    status.classList.add(approved ? "is-ok" : "is-no");
    actionsEl.appendChild(status);

    turn.pendingInterrupt = null;
    resumeTurn(turn, approved);
  }

  // ---- streaming ----

  function consumeStream(response, turn) {
    return new Promise(function (resolve, reject) {
      if (!response.body || typeof response.body.getReader !== "function") {
        resolve();
        return;
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder("utf-8");
      var buffer = "";
      var settled = false;

      function finish(err) {
        if (settled) {
          return;
        }
        settled = true;
        try {
          // reader.cancel() trả về PROMISE — nếu stream đã gãy giữa chừng
          // (proxy cắt, network error), promise này reject và try/catch đồng
          // bộ KHÔNG bắt được → "Uncaught (in promise)" trên console. Phải
          // gắn .catch() trực tiếp lên promise.
          var cancelResult = reader.cancel();
          if (cancelResult && typeof cancelResult.catch === "function") {
            cancelResult.catch(function () {
              /* stream đã lỗi trước đó — bỏ qua */
            });
          }
        } catch (ignore) {
          /* noop */
        }
        if (err) {
          reject(err);
        } else {
          resolve();
        }
      }

      function handleEvent(event) {
        if (!event || typeof event.event !== "string") {
          return; // forward compatibility: ignore unknown frames
        }
        switch (event.event) {
          case "agent":
            setAgent(turn, event.data);
            break;
          case "tool":
            onTool(turn, event.data);
            break;
          case "token":
            onToken(turn, event.data);
            break;
          case "context":
            onContext(turn, event.data);
            break;
          case "interrupt":
            turn.pendingInterrupt = event.data;
            logActivity(turn, "interrupt", "Cần bạn xác nhận trước khi đặt phòng");
            break;
          case "error":
            turn.streamError = event.data;
            break;
          case "done":
            break;
          default:
            break; // ignore gracefully
        }
      }

      function pump() {
        if (settled) {
          return;
        }
        reader
          .read()
          .then(function (chunk) {
            if (settled) {
              return;
            }
            if (chunk.done) {
              finish();
              return;
            }
            buffer += decoder.decode(chunk.value, { stream: true });
            var lines = buffer.split("\n");
            buffer = lines.pop(); // keep the partial final line
            for (var i = 0; i < lines.length; i += 1) {
              var line = lines[i];
              if (line.charCodeAt(line.length - 1) === 13) {
                line = line.slice(0, -1);
              }
              var trimmed = line.trim();
              if (trimmed.indexOf("data:") !== 0) {
                continue;
              }
              var payload = trimmed.slice(5).trim();
              if (!payload) {
                continue;
              }
              var event = null;
              try {
                event = JSON.parse(payload);
              } catch (parseError) {
                continue;
              }
              handleEvent(event);
            }
            pump();
          })
          .catch(function (err) {
            finish(err);
          });
      }

      pump();
    });
  }

  function finishTurn(turn) {
    if (turn.streamError) {
      markError(turn, new Error(String(turn.streamError)));
    } else if (turn.pendingInterrupt) {
      renderHitlCard(turn);
      setPaused(turn);
    } else {
      completeTurn(turn);
    }
  }

  function requestBody(message) {
    var id = currentIdentity();
    return {
      thread_id: state.threadId,
      message: message,
      user_id: id.user_id,
      email: id.email,
    };
  }

  async function sendMessage(message) {
    if (state.streaming) {
      // Never silently swallow a send: tell the user why nothing happened.
      window.UET.ui.toast("Trợ lý đang trả lời. Bấm Dừng nếu bạn muốn gửi câu khác.", "info");
      els.chatInput.focus();
      return;
    }
    if (!state.threadId) {
      state.threadId = randomId();
      state.threadFilled = false;
    }

    if (!state.threadFilled) {
      rememberTitle(state.threadId, message);
      state.threadFilled = true;
    }

    hideEmptyState();
    var turn = createTurn(message);
    state.activeTurn = turn;
    state.controller = new AbortController();
    setStreaming(true);
    setHeaderStatus("Đang xử lý…");
    scrollToBottom(true);

    try {
      var response = await window.UET.api.chat.stream(
        requestBody(message),
        state.controller.signal
      );
      if (!response.ok) {
        await handleHttpError(response, turn);
        return;
      }
      await consumeStream(response, turn);
      finishTurn(turn);
    } catch (err) {
      if (err && err.name === "AbortError") {
        markStopped(turn);
      } else {
        markError(turn, err);
      }
    } finally {
      finishStreaming();
    }
  }

  async function resumeTurn(turn, approved) {
    state.controller = new AbortController();
    setStreaming(true);
    setHeaderStatus("Đang xử lý…");
    // Live again after the HITL pause: reopen the timeline, restart the elapsed
    // counter and say what the user decided, so the resumed work stays visible.
    turn.status = "streaming";
    turn.summaryLabel.textContent = "Đang xử lý…";
    turn.details.open = true;
    turn.details.classList.remove("is-done");
    setTurnLive(turn, true);
    startTurnTimer(turn);
    logActivity(
      turn,
      "resume",
      approved ? "Bạn đã đồng ý — đang xử lý tiếp" : "Bạn đã từ chối — đang xử lý tiếp"
    );
    scrollToBottom(true);

    var id = currentIdentity();
    var body = {
      thread_id: state.threadId,
      decision: { approved: approved },
      user_id: id.user_id,
      email: id.email,
    };

    try {
      var response = await window.UET.api.chat.resume(body, state.controller.signal);
      if (!response.ok) {
        await handleHttpError(response, turn);
        return;
      }
      await consumeStream(response, turn);
      finishTurn(turn);
    } catch (err) {
      if (err && err.name === "AbortError") {
        markStopped(turn);
      } else {
        markError(turn, err);
      }
    } finally {
      finishStreaming();
    }
  }

  function finishStreaming() {
    setStreaming(false);
    state.controller = null;
    if (
      state.activeTurn &&
      (state.activeTurn.status === "done" || state.activeTurn.status === "error")
    ) {
      if (typeof onTurnFinishedCallback === "function") {
        onTurnFinishedCallback(state.threadId);
      }
      state.activeTurn = null;
    }
  }

  async function handleHttpError(response, turn) {
    var detail = "";
    try {
      var body = await response.json();
      detail = body.detail || "";
    } catch (ignore) {
      /* no body */
    }
    if (response.status === 401) {
      window.UET.auth.logout();
      window.UET.ui.toast("Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.", "error");
      return;
    }
    if (response.status === 429) {
      markError(turn, new Error("Quá nhiều yêu cầu. Vui lòng đợi một chút rồi thử lại."));
      return;
    }
    markError(turn, new Error("HTTP " + response.status + (detail ? ": " + detail : "")));
  }

  // ---- saved conversation restore ----

  function renderStaticTurn(userText, assistantContent) {
    var turn = {
      raw: assistantContent || "",
      raf: 0,
      agentName: null,
      agentLabel: "Trợ lý",
      toolChips: {},
      toolCount: 0,
      pendingInterrupt: null,
      streamError: null,
      status: "done",
    };

    var wrap = ui.el("section", "turn");
    var userRow = ui.el("div", "user-row");
    var bubble = ui.el("div", "bubble user");
    bubble.textContent = userText;
    userRow.appendChild(bubble);
    wrap.appendChild(userRow);

    var assist = ui.el("div", "assist");
    var details = ui.el("details", "timeline");
    details.open = false;
    var summary = ui.el("summary", "timeline-summary");
    summary.appendChild(ui.el("span", "ts-label", "Trợ lý"));
    summary.appendChild(ui.el("span", "ts-meta", "đã trả lời"));
    details.appendChild(summary);
    assist.appendChild(details);

    var answerBody = ui.el("div", "markdown-body answer-body");
    answerBody.innerHTML = assistantContent
      ? markdown.render(assistantContent)
      : '<p class="muted">Không có nội dung.</p>';
    assist.appendChild(answerBody);
    wrap.appendChild(assist);

    els.chatLog.appendChild(wrap);
    return turn;
  }

  function clearHistory() {
    stopCurrentStream();
    if (state.activeTurn) {
      stopTurnTimer(state.activeTurn);
      setTurnLive(state.activeTurn, false);
    }
    state.threadId = null;
    // Báo app.js reset nhãn nút "Tóm tắt" khi chuyển/mới cuộc trò chuyện.
    if (window.UET.app && window.UET.app.onConversationOpened) {
      window.UET.app.onConversationOpened();
    }
    state.threadFilled = false;
    state.activeTurn = null;
    els.chatLog.innerHTML = "";
    var empty = ui.el("div", "empty-state");
    empty.id = "empty-state";
    empty.innerHTML = buildEmptyStateHtml();
    els.chatLog.appendChild(empty);
    els.emptyState = empty;
    wireSuggestionChips();
    showEmptyState();
    setHeaderStatus("");
    setStreaming(false);
    els.headerTitle.textContent = "Cuộc trò chuyện mới";
  }

  function buildEmptyStateHtml() {
    return (
      '<div class="empty-hero">' +
      '<div class="empty-mark">' +
      window.UET.ui.svg("spark", "icon") +
      "</div>" +
      '<h2>Hôm nay cần hỗ trợ gì?</h2>' +
      "<p>Tra cứu tri thức UET, tìm phòng phù hợp, quản lý lịch đặt và kiểm chứng thông tin mới.</p>" +
      '<div class="suggestions">' +
      '<button type="button" class="suggestion-chip">Phòng nào có video conference?</button>' +
      '<button type="button" class="suggestion-chip">UET hướng dẫn dùng AI có trách nhiệm thế nào?</button>' +
      '<button type="button" class="suggestion-chip">Tin tức công nghệ mới nhất</button>' +
      "</div>" +
      "</div>"
    );
  }

  function wireSuggestionChips() {
    var chips = els.chatLog.querySelectorAll(".suggestion-chip");
    for (var i = 0; i < chips.length; i += 1) {
      chips[i].addEventListener("click", function () {
        var text = this.textContent;
        els.chatInput.value = text;
        resizeInput();
        els.chatInput.focus();
      });
    }
  }

  function stopCurrentStream() {
    if (state.controller) {
      state.controller.abort();
      state.controller = null;
    }
  }

  async function openConversation(conversationId, title) {
    stopCurrentStream();
    clearHistory();
    state.threadId = conversationId;
    state.threadFilled = true;
    els.headerTitle.textContent = title || "Cuộc trò chuyện";
    hideEmptyState();
    // threadId đã set: báo app.js cập nhật nhãn nút tóm tắt theo job hiện tại
    // (clearHistory cũng gọi hook nhưng lúc đó threadId còn null).
    if (window.UET.app && window.UET.app.onConversationOpened) {
      window.UET.app.onConversationOpened();
    }

    // Lightweight loading placeholder while history loads.
    var loading = ui.el("p", "muted history-loading", "Đang tải cuộc trò chuyện…");
    els.chatLog.appendChild(loading);

    try {
      var messages = await window.UET.api.conversations.messages(conversationId);
      loading.remove();
      if (!messages || !messages.length) {
        showEmptyState();
        return;
      }
      var hasContent = false;
      for (var i = 0; i < messages.length; i += 1) {
        var msg = messages[i];
        if (msg && msg.role === "user") {
          var next = messages[i + 1];
          var assistantText = next && next.role === "assistant" ? next.content : "";
          renderStaticTurn(msg.content, assistantText);
          hasContent = true;
          if (assistantText) {
            i += 1;
          }
        }
      }
      if (!hasContent) {
        showEmptyState();
        return;
      }
      scrollToBottom(true);
    } catch (err) {
      loading.remove();
      showEmptyState();
      window.UET.ui.toast("Không tải được lịch sử trò chuyện.", "error");
    }
  }

  // ---- composer ----

  function resizeInput() {
    els.chatInput.style.height = "auto";
    els.chatInput.style.height = Math.min(els.chatInput.scrollHeight, 200) + "px";
  }

  function submitComposer() {
    var text = els.chatInput.value.trim();
    if (!text || state.streaming) {
      return;
    }
    els.chatInput.value = "";
    resizeInput();
    sendMessage(text);
  }

  function onComposerKeydown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitComposer();
    }
  }

  function init() {
    els.chatLog = document.getElementById("chat-log");
    els.chatScroll = document.getElementById("chat-scroll");
    els.emptyState = document.getElementById("empty-state");
    els.chatForm = document.getElementById("chat-form");
    els.chatInput = document.getElementById("chat-input");
    els.sendBtn = document.getElementById("send-btn");
    els.stopBtn = document.getElementById("stop-btn");
    els.scrollDownBtn = document.getElementById("scroll-down-btn");
    els.headerTitle = document.getElementById("header-title");
    els.headerStatus = document.getElementById("header-status");

    els.chatForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitComposer();
    });
    els.chatInput.addEventListener("keydown", onComposerKeydown);
    els.chatInput.addEventListener("input", resizeInput);

    els.stopBtn.addEventListener("click", function () {
      stopCurrentStream();
    });

    els.chatScroll.addEventListener("scroll", onScroll);
    els.scrollDownBtn.addEventListener("click", resumeAutoScroll);

    wireSuggestionChips();
    resizeInput();
  }

  var onTurnFinishedCallback = null;

  window.UET.chat = {
    init: init,
    newChat: clearHistory,
    openConversation: openConversation,
    currentThreadId: function () {
      return state.threadId;
    },
    isStreaming: function () {
      return state.streaming;
    },
    focusComposer: function () {
      els.chatInput.focus();
      resizeInput();
    },
    set onTurnFinished(fn) {
      onTurnFinishedCallback = fn;
    },
  };
})();
