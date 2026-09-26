/* services/frontend/static/js/app.js
 * Bootstrap: wires auth, chat and the conversation sidebar together, and
 * handles the responsive drawer navigation. */

window.UET = window.UET || {};

(function () {
  "use strict";

  var ui = window.UET.ui;

  var els = {};
  var activeThreadId = null;

  var GENERIC_TITLES = /^\s*(uet assistant conversation|agent conversation|new conversation)\s*$/i;

  function readTitles() {
    try {
      return JSON.parse(localStorage.getItem("uet.titles")) || {};
    } catch (err) {
      return {};
    }
  }

  function displayTitle(conversation) {
    var titles = readTitles();
    if (titles[conversation.conversation_id]) {
      return titles[conversation.conversation_id];
    }
    if (conversation.title && !GENERIC_TITLES.test(conversation.title)) {
      return conversation.title;
    }
    if (conversation.summary) {
      return conversation.summary.slice(0, 60);
    }
    return "Cuộc trò chuyện";
  }

  function formatDate(value) {
    if (!value) {
      return "";
    }
    var date = new Date(value);
    if (isNaN(date.getTime())) {
      return "";
    }
    var now = new Date();
    var sameDay =
      date.getDate() === now.getDate() &&
      date.getMonth() === now.getMonth() &&
      date.getFullYear() === now.getFullYear();
    if (sameDay) {
      return date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" });
  }

  function avatarInitials(name) {
    var parts = String(name || "?")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!parts.length) {
      return "?";
    }
    if (parts.length === 1) {
      return parts[0].slice(0, 2).toUpperCase();
    }
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function renderUserBlock(identity) {
    els.userName.textContent = identity.name;
    els.userEmail.textContent = identity.email || (identity.guest ? "Chế độ khách" : "");
    els.userAvatar.textContent = avatarInitials(identity.name);
    // Only the label text changes — the button keeps its SVG icon, so never
    // touch userAction.textContent (it would drop the icon markup).
    var label = identity.guest ? "Đăng nhập" : "Đăng xuất";
    if (els.userActionLabel) {
      els.userActionLabel.textContent = label;
    }
    els.userAction.dataset.action = identity.guest ? "login" : "logout";
    els.userAction.classList.toggle("is-login", identity.guest);
    els.userAction.setAttribute(
      "aria-label",
      identity.guest ? "Đăng nhập tài khoản" : "Đăng xuất"
    );
  }

  function renderConversationList(list) {
    els.conversationList.innerHTML = "";
    if (!list.length) {
      var empty = ui.el("li", "conversation-empty", "Chưa có cuộc trò chuyện nào.");
      els.conversationList.appendChild(empty);
      return;
    }
    list.forEach(function (conversation) {
      var title = displayTitle(conversation);
      var item = ui.el("li", "conversation-item");
      var button = ui.el("button", "conversation-link");
      button.type = "button";
      button.dataset.id = conversation.conversation_id;
      button.appendChild(ui.el("span", "conversation-title", title));
      button.appendChild(ui.el("span", "conversation-time", formatDate(conversation.updated_at)));
      button.addEventListener("click", function () {
        activeThreadId = conversation.conversation_id;
        window.UET.chat.openConversation(conversation.conversation_id, displayTitle(conversation));
        highlightActive();
        closeSidebar();
      });
      item.appendChild(button);

      // Nút xóa conversation (DELETE /conversations/{id} của conversation service).
      // Nằm NGOÀI button chính (li > button + button) vì HTML cấm button lồng nhau.
      var deleteBtn = ui.el("button", "conversation-delete");
      deleteBtn.type = "button";
      deleteBtn.title = "Xóa cuộc trò chuyện";
      deleteBtn.setAttribute("aria-label", "Xóa cuộc trò chuyện: " + title);
      ui.append(deleteBtn, ui.svg("trash", "icon"));
      deleteBtn.addEventListener("click", function (event) {
        event.stopPropagation();
        removeConversation(conversation.conversation_id, title);
      });
      item.appendChild(deleteBtn);

      els.conversationList.appendChild(item);
    });
    highlightActive();
  }

  async function removeConversation(conversationId, title) {
    var confirmed = window.confirm(
      'Xóa cuộc trò chuyện "' + title + '"? Hành động này không thể hoàn tác.'
    );
    if (!confirmed) {
      return;
    }
    try {
      await window.UET.api.conversations.remove(conversationId);
      ui.toast("Đã xóa cuộc trò chuyện", "success");
      // Nếu đang mở chính conversation bị xóa -> quay về màn hình chat mới.
      if (activeThreadId === conversationId) {
        newChat();
      }
      refreshConversations();
    } catch (err) {
      ui.toast("Xóa thất bại: " + ((err && err.message) || err), "error");
    }
  }

  function highlightActive() {
    var links = els.conversationList.querySelectorAll(".conversation-link");
    for (var i = 0; i < links.length; i += 1) {
      links[i].classList.toggle("is-active", links[i].dataset.id === activeThreadId);
    }
  }

  async function refreshConversations() {
    var identity = window.UET.auth.identity();
    if (!identity) {
      renderConversationList([]);
      return;
    }
    try {
      var list = await window.UET.api.conversations.list(identity.user_id);
      renderConversationList(list || []);
    } catch (err) {
      // 401 = token hết hạn giữa phiên: đăng xuất luôn thay vì im lặng
      // render danh sách trống trong một session đã chết.
      if (err && err.status === 401) {
        window.UET.auth.logout();
        return;
      }
      renderConversationList([]);
    }
  }

  function closeSidebar() {
    document.body.classList.remove("sidebar-open");
  }

  function newChat() {
    activeThreadId = null;
    window.UET.chat.newChat();
    highlightActive();
    closeSidebar();
  }

  function showApp() {
    els.appView.classList.remove("hidden");
  }

  function hideApp() {
    els.appView.classList.add("hidden");
    closeSidebar();
  }

  function onAuthChange(authed, identity) {
    if (authed) {
      els.authView.classList.add("hidden");
      showApp();
      renderUserBlock(identity);
      newChat();
      refreshConversations();
    } else {
      hideApp();
      els.conversationList.innerHTML = "";
    }
  }

  /* ---- Episodic summarize button (bypass ngưỡng 20 tin nhắn) ----
   * Trạng thái nút chính là process indicator: "Đang tóm tắt…" trong lúc
   * chờ service chạy LLM, "Đã tóm tắt ✓" khi hoàn tất, toast báo lỗi khi fail. */
  var SUMMARIZE_LABEL_IDLE = "Tóm tắt cuộc trò chuyện";
  var SUMMARIZE_LABEL_WORKING = "Đang tóm tắt…";
  var SUMMARIZE_LABEL_DONE = "Đã tóm tắt ✓";

  function setSummarizeLabel(text, disabled) {
    els.summarizeLabel.textContent = text;
    els.summarizeBtn.disabled = !!disabled;
  }

  async function summarizeCurrentConversation() {
    var identity = window.UET.auth.identity();
    if (!identity || identity.guest) {
      ui.toast("Đăng nhập để dùng tính năng tóm tắt.", "error");
      return;
    }
    var threadId = window.UET.chat.currentThreadId();
    if (!threadId) {
      ui.toast("Chưa có cuộc trò chuyện nào để tóm tắt.", "info");
      return;
    }
    setSummarizeLabel(SUMMARIZE_LABEL_WORKING, true);
    try {
      // Server trả 202 ngay: job LLM chạy nền ở service, request này KHÔNG
      // giữ kết nối -> app vẫn render messages / chat bình thường.
      var job = await window.UET.api.conversations.summarize(threadId, identity.user_id);
      if (job.state === "done") {
        announceSummarizeDone(job);
        return;
      }
      pollSummarizeStatus(threadId, identity);
    } catch (err) {
      setSummarizeLabel(SUMMARIZE_LABEL_IDLE, false);
      ui.toast("Tóm tắt thất bại: " + ((err && err.message) || err), "error");
    }
  }

  function announceSummarizeDone(job) {
    setSummarizeLabel(SUMMARIZE_LABEL_DONE, false);
    var episode = job.episode || {};
    var preview = typeof episode.title === "string" ? episode.title : "";
    ui.toast(
      "Tóm tắt hoàn tất (" + (job.total_messages || 0) + " tin nhắn)" +
        (preview ? ": " + preview.slice(0, 80) : ""),
      "success"
    );
    // Sidebar title có thể đổi sang summary mới.
    refreshConversations();
  }

  /* Poll job status mỗi 2s cho tới done/error. Chỉ nhãn nút phản ánh process;
   * mọi thao tác khác của app không bị khóa. Dừng im lặng khi đổi conversation. */
  async function pollSummarizeStatus(threadId, identity) {
    for (var i = 0; i < 90; i += 1) {
      await new Promise(function (resolve) {
        setTimeout(resolve, 2000);
      });
      if (window.UET.chat.currentThreadId() !== threadId) {
        return; // user đã sang conversation khác
      }
      try {
        var status = await window.UET.api.conversations.summarizeStatus(
          threadId,
          identity.user_id
        );
        if (status.state === "done") {
          announceSummarizeDone(status);
          return;
        }
        if (status.state === "error") {
          setSummarizeLabel(SUMMARIZE_LABEL_IDLE, false);
          ui.toast("Tóm tắt thất bại: " + (status.error || "lỗi không rõ"), "error");
          return;
        }
      } catch (err) {
        setSummarizeLabel(SUMMARIZE_LABEL_IDLE, false);
        ui.toast("Không kiểm tra được trạng thái tóm tắt: " + ((err && err.message) || err), "error");
        return;
      }
    }
    setSummarizeLabel(SUMMARIZE_LABEL_IDLE, false);
    ui.toast("Tóm tắt chạy quá lâu — thử kiểm tra lại sau.", "info");
  }

  /* Khi mở một conversation: hiển thị đúng trạng thái job còn dang dở. */
  async function refreshSummarizeState() {
    var identity = window.UET.auth.identity();
    var threadId = window.UET.chat.currentThreadId();
    if (!identity || identity.guest || !threadId) {
      return;
    }
    try {
      var status = await window.UET.api.conversations.summarizeStatus(
        threadId,
        identity.user_id
      );
      if (window.UET.chat.currentThreadId() !== threadId) {
        return;
      }
      if (status.state === "running") {
        setSummarizeLabel(SUMMARIZE_LABEL_WORKING, true);
        pollSummarizeStatus(threadId, identity);
      } else if (status.state === "done") {
        setSummarizeLabel(SUMMARIZE_LABEL_DONE, false);
      }
    } catch (err) {
      /* im lặng: trạng thái nút chỉ là tiện ích */
    }
  }

  function init() {
    els.authView = document.getElementById("auth-view");
    els.appView = document.getElementById("app-view");
    els.conversationList = document.getElementById("conversation-list");
    els.userName = document.getElementById("user-name");
    els.userEmail = document.getElementById("user-email");
    els.userAvatar = document.getElementById("user-avatar");
    els.userAction = document.getElementById("user-action");
    els.userActionLabel = document.getElementById("user-action-label");
    els.menuBtn = document.getElementById("menu-btn");
    els.scrim = document.getElementById("scrim");
    els.newChatBtn = document.getElementById("new-chat-btn");
    els.summarizeBtn = document.getElementById("summarize-btn");
    els.summarizeLabel = document.getElementById("summarize-label");

    window.UET.chat.init();

    window.UET.auth.init({
      authView: els.authView,
      authForm: document.getElementById("auth-form"),
      nameField: document.getElementById("name-field"),
      emailInput: document.getElementById("auth-email"),
      passwordInput: document.getElementById("auth-password"),
      submitBtn: document.getElementById("auth-submit"),
      switchLink: document.getElementById("auth-switch-btn"),
      switchText: document.getElementById("auth-switch-text"),
      errorBox: document.getElementById("auth-error"),
      guestBtn: document.getElementById("guest-btn"),
      authTitle: document.getElementById("auth-title"),
      authSubtitle: document.getElementById("auth-subtitle"),
    });

    window.UET.auth.onAuthChange(onAuthChange);

    window.UET.chat.onTurnFinished = function () {
      refreshConversations();
    };

    els.newChatBtn.addEventListener("click", newChat);
    els.summarizeBtn.addEventListener("click", summarizeCurrentConversation);

    // chat.js gọi hook này mỗi lần mở/mới cuộc trò chuyện để reset nhãn nút.
    window.UET.app = {
      onConversationOpened: function () {
        setSummarizeLabel(SUMMARIZE_LABEL_IDLE, false);
        refreshSummarizeState();
      },
    };
    els.menuBtn.addEventListener("click", function () {
      document.body.classList.toggle("sidebar-open");
    });
    els.scrim.addEventListener("click", closeSidebar);
    els.userAction.addEventListener("click", function () {
      // Guest sessions get "Đăng nhập": show the auth screen but keep the local
      // guest id, so the sidebar history is still there if they cancel.
      if (els.userAction.dataset.action === "login") {
        hideApp();
        window.UET.auth.showAuth();
        return;
      }
      window.UET.auth.logout();
    });

    // Bootstrap: signed-in (or guest) -> app, otherwise the auth view already
    // shows by default. With a stored JWT we validate it FIRST: firing data
    // requests (conversations) with an expired token only produces doomed
    // 401s in the console before the inevitable logout.
    var identity = window.UET.auth.identity();
    if (identity) {
      if (identity.guest) {
        onAuthChange(true, identity);
      } else {
        window.UET.api.identity
          .me()
          .then(function () {
            onAuthChange(true, identity);
          })
          .catch(function (err) {
            if (err && err.status === 401) {
              window.UET.auth.logout();
              return;
            }
            // Transient network failures are ignored (session kept), same
            // as before — the app still opens and retries on next action.
            onAuthChange(true, identity);
          });
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();