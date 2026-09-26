/* services/frontend/static/js/markdown.js
 * A SMALL, SAFE markdown renderer.
 *
 * XSS law: every piece of model text is HTML-escaped FIRST, then a few
 * controlled inline/block constructs are introduced. The only markup we emit
 * is our own fixed tags (<strong>, <em>, <code>, <a>, <li>, <pre>...), and
 * link hrefs are restricted to http/https/mailto. We never pass raw model
 * text to innerHTML. */

window.UET = window.UET || {};

(function () {
  "use strict";

  var SAFE_URL = /^(https?:|mailto:)/i;

  // Sentinel characters used to protect inline code and fenced blocks while
  // the rest of the line is transformed. These are control characters that
  // never survive escapeHtml() into user-visible text unescaped, so they
  // cannot collide with model output.
  var CODE_TOKEN = "\u0000";
  var FENCE_TOKEN = "\u0001";

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* Render inline markdown on already-escaped text. */
  function renderInline(text) {
    // Inline code first so its content is not touched by emphasis transforms.
    var codes = [];
    text = text.replace(/`([^`\n]+)`/g, function (_, code) {
      codes.push("<code>" + code + "</code>");
      return CODE_TOKEN + (codes.length - 1) + CODE_TOKEN;
    });

    // Links (label may contain emphasis, handled by subsequent passes).
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_, label, url) {
      if (SAFE_URL.test(url)) {
        return (
          '<a href="' +
          url +
          '" target="_blank" rel="noopener noreferrer nofollow">' +
          label +
          "</a>"
        );
      }
      return label;
    });

    // Emphasis (bold before italic so ** and * don't collide).
    text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/\*([^*\s][^*\n]*?[^*\s]|[^*\s])\*(?!\*)/g, "<em>$1</em>");
    text = text.replace(/~~([^~]+)~~/g, "<del>$1</del>");

    // Restore inline code placeholders.
    var codePattern = new RegExp(CODE_TOKEN + "(\\d+)" + CODE_TOKEN, "g");
    text = text.replace(codePattern, function (_, index) {
      return codes[Number(index)];
    });

    return text;
  }

  /* ---- GFM tables (industry-standard markdown extension) ----
   * A table = header row containing '|', a divider row of dashes
   * (|---|:---:|), then body rows. Column alignment from the divider is
   * intentionally ignored to keep this renderer small; cells follow the
   * same XSS law as everything else: escapeHtml() first, renderInline() after. */

  function isTableRow(line) {
    return line.indexOf("|") !== -1;
  }

  function isTableDivider(line) {
    // Divider row like |---|:---:|---| : only pipes, dashes, colons and
    // spaces, with at least one dash. (Same shape GFM accepts.)
    return line.indexOf("-") !== -1 && /^[\s|:-]+$/.test(line);
  }

  function splitTableCells(line) {
    // Drop one leading and one trailing pipe, then split. Escaped pipes (\|)
    // are not supported — model output rarely contains them and supporting
    // them would complicate the splitter.
    var stripped = line.replace(/^\|/, "").replace(/\|$/, "");
    var cells = stripped.split("|");
    for (var i = 0; i < cells.length; i += 1) {
      cells[i] = cells[i].trim();
    }
    return cells;
  }

  function renderTable(headerCells, bodyRows) {
    var html = "<table><thead><tr>";
    for (var h = 0; h < headerCells.length; h += 1) {
      html += "<th>" + renderInline(escapeHtml(headerCells[h])) + "</th>";
    }
    html += "</tr></thead><tbody>";
    for (var r = 0; r < bodyRows.length; r += 1) {
      html += "<tr>";
      for (var c = 0; c < headerCells.length; c += 1) {
        // Missing trailing cells render empty instead of "undefined".
        var cell = bodyRows[r][c] !== undefined ? bodyRows[r][c] : "";
        html += "<td>" + renderInline(escapeHtml(cell)) + "</td>";
      }
      html += "</tr>";
    }
    html += "</tbody></table>";
    return html;
  }

  function renderMarkdown(src) {
    if (src == null) {
      return "";
    }
    var text = String(src);

    // Extract fenced code blocks first (content fully escaped, kept verbatim).
    var fences = [];
    text = text.replace(/```([\w+-]*)[ \t]*\n?([\s\S]*?)```/g, function (_, lang, code) {
      var langAttr = lang ? ' class="language-' + escapeHtml(lang) + '"' : "";
      fences.push(
        "<pre><code" + langAttr + ">" + escapeHtml(code.replace(/\n$/, "")) + "</code></pre>"
      );
      return FENCE_TOKEN + (fences.length - 1) + FENCE_TOKEN;
    });

    var lines = text.split("\n");
    var html = "";
    var listType = null; // null | "ul" | "ol"
    var para = [];
    var quote = [];

    function flushList() {
      if (listType) {
        html += "</" + listType + ">";
        listType = null;
      }
    }
    function flushPara() {
      if (para.length) {
        html += "<p>" + renderInline(escapeHtml(para.join(" "))) + "</p>";
        para = [];
      }
    }
    function flushQuote() {
      if (quote.length) {
        html += "<blockquote>" + renderInline(escapeHtml(quote.join(" "))) + "</blockquote>";
        quote = [];
      }
    }
    function flushAll() {
      flushPara();
      flushQuote();
      flushList();
    }

    var fencePattern = new RegExp("^" + FENCE_TOKEN + "(\\d+)" + FENCE_TOKEN + "$");

    for (var i = 0; i < lines.length; i += 1) {
      var raw = lines[i];
      var trimmed = raw.trim();

      if (!trimmed) {
        flushAll();
        continue;
      }

      var fence = trimmed.match(fencePattern);
      if (fence) {
        flushAll();
        html += fences[Number(fence[1])] || "";
        continue;
      }

      var heading = trimmed.match(/^(#{1,3})\s+(.*)$/);
      if (heading) {
        flushAll();
        var level = heading[1].length;
        html += "<h" + level + ">" + renderInline(escapeHtml(heading[2])) + "</h" + level + ">";
        continue;
      }

      if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
        flushAll();
        html += "<hr>";
        continue;
      }

      // Table block: current line has '|', NEXT line is a GFM divider row.
      if (isTableRow(trimmed) && i + 1 < lines.length && isTableDivider(lines[i + 1].trim())) {
        flushAll();
        var headerCells = splitTableCells(trimmed);
        var bodyRows = [];
        i += 2; // consume header + divider
        while (i < lines.length && lines[i].trim() && isTableRow(lines[i].trim())) {
          bodyRows.push(splitTableCells(lines[i].trim()));
          i += 1;
        }
        i -= 1; // the for-loop's i += 1 lands on the first non-table line
        html += renderTable(headerCells, bodyRows);
        continue;
      }

      var quoteMatch = trimmed.match(/^>\s?(.*)$/);
      if (quoteMatch) {
        flushPara();
        flushList();
        quote.push(quoteMatch[1]);
        continue;
      }

      var bullet = trimmed.match(/^[-*+]\s+(.*)$/);
      var ordered = trimmed.match(/^\d+[.)]\s+(.*)$/);
      if (bullet || ordered) {
        var isOrdered = !!ordered;
        var content = isOrdered ? ordered[1] : bullet[1];
        flushPara();
        flushQuote();
        var wantedType = isOrdered ? "ol" : "ul";
        if (listType !== wantedType) {
          flushList();
          html += "<" + wantedType + ">";
          listType = wantedType;
        }
        html += "<li>" + renderInline(escapeHtml(content)) + "</li>";
        continue;
      }

      flushList();
      flushQuote();
      para.push(trimmed);
    }

    flushAll();
    return html;
  }

  window.UET.markdown = { render: renderMarkdown };
})();