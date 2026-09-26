/* services/frontend/static/js/ui.js
 * Small DOM helpers, inline SVG icons and a toast, shared by the other modules.
 * All icons are hand-written static SVG strings — never user data. */

window.UET = window.UET || {};

(function () {
  "use strict";

  var ICONS = {
    plus: '<path d="M12 5v14M5 12h14"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    send: '<path d="M22 2L11 13M22 2l-7 20-4-9-9-4z"/>',
    stop: '<rect x="7" y="7" width="10" height="10" rx="1.5"/>',
    check: '<path d="M5 13l4 4L19 7"/>',
    down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
    logOut: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8"/>',
    shield: '<path d="M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6z"/>',
    upload: '<path d="M12 16V4M6 10l6-6 6 6"/><path d="M20 16v3a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3"/>',
  };

  function svg(name, cls) {
    return (
      '<svg class="' +
      (cls || "icon") +
      '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      ICONS[name] +
      "</svg>"
    );
  }

  /* Create an element with an optional class and text (textContent, always safe). */
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) {
      node.className = cls;
    }
    if (text != null) {
      node.textContent = text;
    }
    return node;
  }

  /* Append trusted markup (our own SVG/element scaffolding) to a parent and return
   * the last inserted element. NEVER pass raw model/agent text here. */
  function append(parent, html) {
    parent.insertAdjacentHTML("beforeend", html);
    return parent.lastElementChild;
  }

  var toastTimer = null;
  function toast(message, kind) {
    var t = document.getElementById("toast");
    if (!t) {
      return;
    }
    t.textContent = message;
    t.className = "toast " + (kind || "info");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      t.classList.add("hidden");
    }, 3600);
  }

  window.UET.ui = { svg: svg, el: el, append: append, toast: toast };
})();