/* services/frontend/static/js/api.js
 * API client for identity, agent and conversation services.
 *
 * Mode resolution:
 *   - gateway: window.APP_CONFIG.gatewayBaseUrl non-empty -> all calls go to
 *     the Kong gateway (CORS + JWT), Authorization: Bearer attached.
 *   - proxy:   APP_CONFIG.proxyGateway true + empty base -> same-origin
 *     relative paths proxied by nginx to the gateway.
 *   - direct:  otherwise -> local dev, calls hit the microservices on
 *     localhost directly. */

window.UET = window.UET || {};

(function () {
  "use strict";

  var CONFIG = window.APP_CONFIG || {
    gatewayBaseUrl: "",
    proxyGateway: false,
    direct: {
      agent: "http://localhost:8000",
      identity: "http://localhost:8001",
      conversation: "http://localhost:8004",
      rag: "http://localhost:8002",
    },
  };

  var SESSION_KEY = "uet.session";

  function mode() {
    if (CONFIG.gatewayBaseUrl) {
      return "gateway";
    }
    if (CONFIG.proxyGateway) {
      return "proxy";
    }
    return "direct";
  }

  function stripTrailing(value) {
    return String(value || "").replace(/\/+$/, "");
  }

  function serviceBase(name) {
    if (mode() === "gateway") {
      return stripTrailing(CONFIG.gatewayBaseUrl);
    }
    if (mode() === "proxy") {
      return "";
    }
    return stripTrailing((CONFIG.direct || {})[name]);
  }

  function token() {
    try {
      var raw = localStorage.getItem(SESSION_KEY);
      if (!raw) {
        return null;
      }
      var session = JSON.parse(raw);
      return session.token || null;
    } catch (err) {
      return null;
    }
  }

  function authHeader() {
    var t = token();
    return t ? { Authorization: "Bearer " + t } : {};
  }

  function jsonHeaders(extra) {
    var headers = { "Content-Type": "application/json" };
    var auth = authHeader();
    Object.keys(auth).forEach(function (key) {
      headers[key] = auth[key];
    });
    Object.keys(extra || {}).forEach(function (key) {
      headers[key] = extra[key];
    });
    return headers;
  }

  /* FastAPI reports validation failures as an array of {loc, msg} objects;
   * flatten them into one human readable line for the UI. */
  function detailMessage(body, status) {
    var detail = body ? body.detail : null;
    if (Array.isArray(detail)) {
      var parts = detail.map(function (item) {
        var loc = item && Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        var msg = (item && (item.msg || item.message)) || "Giá trị không hợp lệ";
        return loc ? loc + ": " + msg : msg;
      });
      if (parts.length) {
        return parts.join("; ");
      }
    }
    if (typeof detail === "string" && detail) {
      return detail;
    }
    return "HTTP " + status;
  }

  /* Resolve a JSON response, mapping non-2xx to an Error with .status/.detail. */
  function handleJson(res) {
    return res
      .json()
      .catch(function () {
        return {};
      })
      .then(function (body) {
        if (!res.ok) {
          var message = detailMessage(body, res.status);
          var err = new Error(message);
          err.status = res.status;
          err.detail = message;
          throw err;
        }
        return body;
      });
  }

  var identity = {
    register: function (payload) {
      return fetch(serviceBase("identity") + "/auth/register", {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }).then(handleJson);
    },
    login: function (payload) {
      return fetch(serviceBase("identity") + "/auth/login", {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(payload),
      }).then(handleJson);
    },
    me: function () {
      return fetch(serviceBase("identity") + "/auth/me", {
        method: "GET",
        headers: authHeader(),
      }).then(handleJson);
    },
  };

  var conversations = {
    list: function (userId) {
      return fetch(
        serviceBase("conversation") + "/conversations?user_id=" + encodeURIComponent(userId),
        { method: "GET", headers: authHeader() }
      ).then(handleJson);
    },
    messages: function (conversationId) {
      return fetch(
        serviceBase("conversation") +
          "/conversations/" +
          encodeURIComponent(conversationId) +
          "/messages",
        { method: "GET", headers: authHeader() }
      ).then(handleJson);
    },
    remove: function (conversationId) {
      return fetch(
        serviceBase("conversation") +
          "/conversations/" +
          encodeURIComponent(conversationId),
        { method: "DELETE", headers: authHeader() }
      ).then(handleJson);
    },
    /* Force episodic summarize now (bypass the 20-message threshold).
     * Returns 202 + job state; poll summarizeStatus until done/error. */
    summarize: function (conversationId, userId) {
      return fetch(
        serviceBase("conversation") +
          "/conversations/" +
          encodeURIComponent(conversationId) +
          "/summarize?user_id=" +
          encodeURIComponent(userId || ""),
        { method: "POST", headers: authHeader() }
      ).then(handleJson);
    },
    summarizeStatus: function (conversationId, userId) {
      return fetch(
        serviceBase("conversation") +
          "/conversations/" +
          encodeURIComponent(conversationId) +
          "/summarize/status?user_id=" +
          encodeURIComponent(userId || ""),
        { method: "GET", headers: authHeader() }
      ).then(handleJson);
    },
  };

  /* Chat returns the raw fetch Response so callers can drive the SSE stream. */
  var chat = {
    stream: function (body, signal) {
      return fetch(serviceBase("agent") + "/api/chat/stream", {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(body),
        signal: signal,
      });
    },
    resume: function (body, signal) {
      return fetch(serviceBase("agent") + "/api/chat/resume", {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(body),
        signal: signal,
      });
    },
  };

  window.UET.api = {
    mode: mode,
    token: token,
    serviceBase: serviceBase,
    identity: identity,
    conversations: conversations,
    chat: chat,
  };
})();