/* Text-first architecture overview. No external diagram images are required. */

window.UET = window.UET || {};

(function () {
  "use strict";

  var ui = window.UET.ui;
  var FLOWS = [
    {
      title: "Luồng yêu cầu",
      nodes: ["Trình duyệt / CLI", "Kong + JWT", "LangGraph router", "Agent chuyên trách"],
      detail: "Gateway xác thực trước khi router chọn đúng một nhánh FAQ, web, booking hoặc trò chuyện.",
    },
    {
      title: "Tri thức UET",
      nodes: ["Câu hỏi", "Qdrant cache", "Dense + BM25 + RRF", "Rerank + MMR", "Câu trả lời có căn cứ"],
      detail: "HyDE chỉ chạy khi điểm truy hồi thấp. Dữ liệu hiện tại là tài liệu tham chiếu UET, không phải quy định chính thức.",
    },
    {
      title: "Đặt phòng an toàn",
      nodes: ["Registry phòng", "Kiểm tra trạng thái", "Kiểm tra trùng lịch", "Người dùng phê duyệt", "Postgres"],
      detail: "Mọi thao tác ghi đều dừng để xác nhận; ownership và xung đột được kiểm tra trước khi thay đổi dữ liệu.",
    },
    {
      title: "Hội thoại và bộ nhớ",
      nodes: ["SSE", "Lịch sử", "Tóm tắt theo thread", "Redis exact cache", "Postgres"],
      detail: "Mỗi thread có tóm tắt riêng. Dữ liệu bộ nhớ được coi là dữ liệu không tin cậy, không phải chỉ dẫn.",
    },
  ];

  var els = {};

  function renderFlow(flow) {
    var section = ui.el("section", "arch-card");
    var heading = ui.el("h3", "arch-title", flow.title);
    var diagram = ui.el("div", "arch-flow");

    flow.nodes.forEach(function (label, index) {
      diagram.appendChild(ui.el("span", "arch-node", label));
      if (index < flow.nodes.length - 1) {
        diagram.appendChild(ui.el("span", "arch-arrow", "→"));
      }
    });

    section.appendChild(heading);
    section.appendChild(diagram);
    section.appendChild(ui.el("p", "arch-detail", flow.detail));
    return section;
  }

  function renderList() {
    els.list.replaceChildren();
    FLOWS.forEach(function (flow) {
      els.list.appendChild(renderFlow(flow));
    });
  }

  function openModal() {
    renderList();
    els.modal.classList.remove("hidden");
    document.body.classList.add("modal-open");
  }

  function closeModal() {
    els.modal.classList.add("hidden");
    document.body.classList.remove("modal-open");
  }

  function init() {
    els.modal = document.getElementById("arch-modal");
    els.list = document.getElementById("arch-list");
    var openButton = document.getElementById("arch-open-btn");
    var closeButton = document.getElementById("arch-close-btn");
    if (!els.modal || !els.list || !openButton) {
      return;
    }

    openButton.addEventListener("click", openModal);
    if (closeButton) {
      closeButton.addEventListener("click", closeModal);
    }

    var backdrop = els.modal.querySelector(".modal-backdrop");
    if (backdrop) {
      backdrop.addEventListener("click", closeModal);
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !els.modal.classList.contains("hidden")) {
        closeModal();
      }
    });
  }

  window.UET.architecture = { init: init };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

