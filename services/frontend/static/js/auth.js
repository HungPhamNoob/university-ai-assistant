/* services/frontend/static/js/auth.js
 * Session store + the login/register/guest screen.
 *
 * A logged-in session is the identity AuthResponse:
 *   { token, token_type, user: { user_id, email, name, created_at } }
 * stored under localStorage "uet.session".
 *
 * A guest is a client-only anonymous identity "uet.guest":
 *   { user_id: "anon-<uuid>" }
 * Guests are "trivially safe": no server credential, just a locally generated
 * id used as the chat user_id and the conversation owner filter. */

window.UET = window.UET || {};

(function () {
  "use strict";

  var SESSION_KEY = "uet.session";
  var GUEST_KEY = "uet.guest";

  var authForm = null;
  var authView = null;
  var nameField = null;
  var emailInput = null;
  var passwordInput = null;
  var submitBtn = null;
  var switchLink = null;
  var switchText = null;
  var errorBox = null;
  var guestBtn = null;
  var authTitle = null;
  var authSubtitle = null;
  var modeLine = null;
  var tabLogin = null;
  var tabRegister = null;
  var submitLabel = null;
  var nameInput = null;
  var togglePasswordBtn = null;
  var passwordHint = null;
  var passwordMeter = null;
  var fieldErrors = {}; // input element -> its <p class="field-error">

  /* Validation mirrors services/identity/users/schemas.py so the browser and the
   * service agree: same email pattern, password >= 6 chars, name required. */
  var EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
  var MIN_PASSWORD = 6;

  var currentMode = "login"; // "login" | "register"
  var authChanged = null; // callback(appIsReady: boolean)

  function readJson(key) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (err) {
      return null;
    }
  }

  function getSession() {
    return readJson(SESSION_KEY);
  }

  function setSession(session) {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  }

  function clearSession() {
    localStorage.removeItem(SESSION_KEY);
  }

  function getGuest() {
    return readJson(GUEST_KEY);
  }

  function ensureGuest() {
    var guest = getGuest();
    if (guest && guest.user_id) {
      return guest;
    }
    var id = "anon-" + cryptoRandomId();
    guest = { user_id: id };
    localStorage.setItem(GUEST_KEY, JSON.stringify(guest));
    return guest;
  }

  function clearGuest() {
    localStorage.removeItem(GUEST_KEY);
  }

  function cryptoRandomId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === "x" ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function token() {
    var session = getSession();
    return session ? session.token || null : null;
  }

  function isLoggedIn() {
    return !!getSession();
  }

  /* The active identity (account or guest), or null when signed out. */
  function identity() {
    var session = getSession();
    if (session && session.user) {
      return {
        user_id: session.user.user_id,
        email: session.user.email,
        name: session.user.name,
        guest: false,
      };
    }
    var guest = getGuest();
    if (guest && guest.user_id) {
      return {
        user_id: guest.user_id,
        email: null,
        name: "Khách",
        guest: true,
      };
    }
    return null;
  }

  /* ---- view plumbing ---- */

  function setMode(mode) {
    currentMode = mode;
    var registering = mode === "register";
    nameField.classList.toggle("hidden", !registering);
    submitLabel.textContent = registering ? "Tạo tài khoản" : "Đăng nhập";
    authTitle.textContent = registering ? "Tạo tài khoản" : "Chào mừng trở lại";
    authSubtitle.textContent = registering
      ? "Đăng ký để lưu lịch sử trò chuyện và đặt phòng họp."
      : "Đăng nhập để tiếp tục với trợ lý AI của bạn.";
    switchText.textContent = registering ? "Đã có tài khoản?" : "Chưa có tài khoản?";
    switchLink.textContent = registering ? "Đăng nhập" : "Đăng ký";
    passwordInput.autocomplete = registering ? "new-password" : "current-password";

    // Tabs are the primary affordance: keep them in sync with the text link.
    if (tabLogin && tabRegister) {
      tabLogin.classList.toggle("is-selected", !registering);
      tabRegister.classList.toggle("is-selected", registering);
      tabLogin.setAttribute("aria-selected", registering ? "false" : "true");
      tabRegister.setAttribute("aria-selected", registering ? "true" : "false");
    }
    // The strength hint only matters while creating a password.
    if (passwordHint) {
      passwordHint.classList.toggle("hidden", !registering);
    }
    updateMeter();
    clearFieldErrors();
    clearError();
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  function setFieldError(input, message) {
    var box = input ? fieldErrors[input.id] : null;
    if (!box) {
      return;
    }
    if (message) {
      box.textContent = message;
      box.classList.remove("hidden");
      input.classList.add("is-invalid");
      input.setAttribute("aria-invalid", "true");
    } else {
      box.textContent = "";
      box.classList.add("hidden");
      input.classList.remove("is-invalid");
      input.removeAttribute("aria-invalid");
    }
  }

  function clearFieldErrors() {
    Object.keys(fieldErrors).forEach(function (id) {
      setFieldError(document.getElementById(id), "");
    });
  }

  /* 0..3 password strength score — a client-side hint, never a rule. */
  function passwordScore(value) {
    var score = 0;
    if (value.length >= MIN_PASSWORD) {
      score += 1;
    }
    if (value.length >= 10) {
      score += 1;
    }
    if (/[A-Z]/.test(value) && /[a-z]/.test(value)) {
      score += 1;
    }
    if (/[0-9]/.test(value) || /[^A-Za-z0-9]/.test(value)) {
      score += 1;
    }
    return Math.min(score, 3);
  }

  function updateMeter() {
    if (!passwordMeter) {
      return;
    }
    var value = passwordInput.value || "";
    if (currentMode !== "register" || !value) {
      passwordMeter.className = "pw-meter hidden";
      return;
    }
    var score = passwordScore(value);
    var bar = passwordMeter.firstElementChild;
    passwordMeter.className = "pw-meter s" + score;
    if (bar) {
      bar.style.width = ["25%", "45%", "70%", "100%"][score];
    }
    passwordMeter.title = ["Rất yếu", "Yếu", "Khá", "Tốt"][score];
  }

  /* Validate the visible fields. Returns the first invalid input, or null. */
  function validateForm() {
    var email = emailInput.value.trim();
    var password = passwordInput.value;
    clearFieldErrors();

    if (!email) {
      setFieldError(emailInput, "Vui lòng nhập email.");
      return emailInput;
    }
    if (!EMAIL_RE.test(email)) {
      setFieldError(emailInput, "Email không đúng định dạng (ví dụ: ten@uet.com.vn).");
      return emailInput;
    }
    if (!password) {
      setFieldError(passwordInput, "Vui lòng nhập mật khẩu.");
      return passwordInput;
    }
    if (currentMode === "register") {
      if (password.length < MIN_PASSWORD) {
        setFieldError(passwordInput, "Mật khẩu cần tối thiểu " + MIN_PASSWORD + " ký tự.");
        return passwordInput;
      }
      if (nameInput && !nameInput.value.trim()) {
        setFieldError(nameInput, "Vui lòng nhập họ và tên.");
        return nameInput;
      }
    }
    return null;
  }

  function setBusy(busy) {
    submitBtn.disabled = busy;
    guestBtn.disabled = busy;
    switchLink.disabled = busy;
    if (tabLogin) {
      tabLogin.disabled = busy;
    }
    if (tabRegister) {
      tabRegister.disabled = busy;
    }
    emailInput.disabled = busy;
    passwordInput.disabled = busy;
    if (nameInput) {
      nameInput.disabled = busy;
    }
    submitBtn.classList.toggle("is-busy", busy);
    if (busy) {
      submitBtn.dataset.label = submitLabel.textContent;
      submitLabel.textContent = "Đang xử lý…";
    } else if (submitBtn.dataset.label) {
      submitLabel.textContent = submitBtn.dataset.label;
    }
  }

  /* Map backend detail strings to friendly Vietnamese messages. */
  function friendlyAuthError(status, detail) {
    var d = String(detail || "").toLowerCase();
    if (status === 409) {
      return "Email này đã được đăng ký. Hãy đăng nhập hoặc dùng email khác.";
    }
    if (status === 401) {
      return "Email hoặc mật khẩu không đúng.";
    }
    if (status === 422) {
      return detail
        ? "Thông tin nhập chưa hợp lệ: " + detail
        : "Thông tin nhập chưa hợp lệ. Kiểm tra lại email và mật khẩu (tối thiểu 6 ký tự).";
    }
    if (/networkerror|failed to fetch|typeerror/.test(d)) {
      return "Không kết nối được tới dịch vụ xác thực. Kiểm tra backend đang chạy.";
    }
    return "Đăng nhập thất bại. Vui lòng thử lại.";
  }

  function submitAction() {
    var email = emailInput.value.trim();
    var password = passwordInput.value;
    var name = "";

    // Inline validation first: one wrong field should not need a server round trip.
    var invalid = validateForm();
    if (invalid) {
      clearError();
      invalid.focus();
      return;
    }
    if (currentMode === "register") {
      name = nameInput ? nameInput.value.trim() : "";
    }
    clearError();
    setBusy(true);

    var registering = currentMode === "register";
    var action = registering
      ? window.UET.api.identity.register({ email: email, password: password, name: name })
      : window.UET.api.identity.login({ email: email, password: password });

    action
      .then(function (response) {
        setSession(response);
        window.UET.ui.toast(
          registering
            ? "Đã tạo tài khoản cho " + email + "."
            : "Đăng nhập thành công: " + ((response.user && response.user.name) || email),
          "success"
        );
        enterApp(true);
      })
      .catch(function (err) {
        showError(friendlyAuthError(err.status, err.detail || err.message));
      })
      .finally(function () {
        setBusy(false);
      });
  }

  function enterApp(fromAuth) {
    authView.classList.add("hidden");
    if (typeof authChanged === "function") {
      authChanged(true, identity(), fromAuth);
    }
  }

  function showAuth(message) {
    authForm.reset();
    clearError();
    clearFieldErrors();
    updateMeter();
    authView.classList.remove("hidden");
    if (message) {
      showError(message);
    }
    // Focus the email field once the view is visible.
    setTimeout(function () {
      emailInput.focus();
    }, 0);
  }

  function logout() {
    clearSession();
    clearGuest();
    if (typeof authChanged === "function") {
      authChanged(false, null, false);
    }
    showAuth();
  }

  function init(refs) {
    authView = refs.authView;
    authForm = refs.authForm;
    nameField = refs.nameField;
    emailInput = refs.emailInput;
    passwordInput = refs.passwordInput;
    submitBtn = refs.submitBtn;
    switchLink = refs.switchLink;
    switchText = refs.switchText;
    errorBox = refs.errorBox;
    guestBtn = refs.guestBtn;
    authTitle = refs.authTitle;
    authSubtitle = refs.authSubtitle;

    // New UX hooks (all optional: the form still works when they are missing).
    nameInput = document.getElementById("auth-name");
    submitLabel = submitBtn.querySelector(".btn-label") || submitBtn;
    tabLogin = document.getElementById("auth-tab-login");
    tabRegister = document.getElementById("auth-tab-register");
    togglePasswordBtn = document.getElementById("auth-toggle-password");
    passwordHint = document.getElementById("auth-password-hint");
    passwordMeter = document.getElementById("auth-password-meter");
    fieldErrors = {
      "auth-name": document.getElementById("auth-name-error"),
      "auth-email": document.getElementById("auth-email-error"),
      "auth-password": document.getElementById("auth-password-error"),
    };

    modeLine = document.getElementById("auth-mode-line");
    if (modeLine) {
      var labels = {
        direct: "Kết nối trực tiếp (phát triển)",
        gateway: "Kết nối qua cổng gateway",
        proxy: "Kết nối qua cổng gateway (proxy)",
      };
      modeLine.textContent = labels[window.UET.api.mode()] || "";
    }

    // Guest chỉ hữu ích ở direct mode (không gateway): sau Kong, mọi request
    // không JWT đều 401 → ẩn nút guest để user không rơi vào ngõ cụt.
    if (window.UET.api.mode() !== "direct") {
      if (guestBtn) {
        guestBtn.classList.add("hidden");
      }
      var guestHint = document.getElementById("guest-hint");
      if (guestHint) {
        guestHint.classList.add("hidden");
      }
    }

    authForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitAction();
    });

    switchLink.addEventListener("click", function () {
      setMode(currentMode === "login" ? "register" : "login");
    });

    if (tabLogin) {
      tabLogin.addEventListener("click", function () {
        setMode("login");
      });
    }
    if (tabRegister) {
      tabRegister.addEventListener("click", function () {
        setMode("register");
      });
    }

    if (togglePasswordBtn) {
      togglePasswordBtn.addEventListener("click", function () {
        var show = passwordInput.type === "password";
        passwordInput.type = show ? "text" : "password";
        togglePasswordBtn.setAttribute("aria-pressed", show ? "true" : "false");
        togglePasswordBtn.setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
        togglePasswordBtn.classList.toggle("is-on", show);
        passwordInput.focus();
      });
    }

    // Errors disappear as soon as the user fixes the field; Enter in the name
    // field moves to email instead of submitting a half-filled form.
    [nameInput, emailInput, passwordInput].forEach(function (input) {
      if (!input) {
        return;
      }
      input.addEventListener("input", function () {
        setFieldError(input, "");
        clearError();
        if (input === passwordInput) {
          updateMeter();
        }
      });
      if (input === nameInput) {
        input.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            event.preventDefault();
            emailInput.focus();
          }
        });
      }
    });

    guestBtn.addEventListener("click", function () {
      ensureGuest();
      enterApp(true);
    });

    setMode("login");
  }

  window.UET.auth = {
    init: init,
    setMode: setMode,
    showAuth: showAuth,
    logout: logout,
    isLoggedIn: isLoggedIn,
    identity: identity,
    token: token,
    onAuthChange: function (fn) {
      authChanged = fn;
    },
  };
})();