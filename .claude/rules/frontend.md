# Frontend / UI — chọn skill phù hợp theo task

> Load khi đụng tới file frontend/UI (html, css, js, artifacts...). Ngoài `coding-simple`
> (vẫn áp dụng cho phần code), với công việc frontend/UI thì chọn skill theo bảng sau:

| Tình huống | Skill dùng |
|---|---|
| Cần định hướng thẩm mỹ: thiết kế giao diện có bản sắc riêng, chọn palette, typography, layout, tránh giao diện trông "template" | `frontend-design` |
| Cần dữ liệu UI/UX để tra cứu: style theo loại sản phẩm, color palette, font pairing, UX guidelines (accessibility, touch, form...), hướng dẫn theo stack cụ thể (react, nextjs, vue, html-tailwind...) | `ui-ux-pro-max` |
| Cần xây artifact web phức tạp cho claude.ai: nhiều component, state management, routing, React + Tailwind + shadcn/ui đóng gói thành 1 file HTML | `web-artifacts-builder` |

Gợi ý phối hợp khi làm một giao diện hoàn chỉnh:

1. `ui-ux-pro-max` → chạy `--design-system` để lấy style/color/typography phù hợp sản phẩm,
   và tra UX guidelines bằng `search.py --domain <domain>`.
2. `frontend-design` → tinh chỉnh quyết định thẩm mỹ để giao diện có điểm nhấn riêng, không rập khuôn.
3. `coding-simple` → áp dụng khi viết code component.
4. Artifact đơn giản 1 file HTML/JSX thì **không** cần `web-artifacts-builder` — skill đó chỉ dành
   cho artifact phức tạp nhiều component.

Skills nằm trong `.claude/skills/` — gọi bằng tên (ví dụ `/coding-simple`)
hoặc tự load qua Skill tool khi task trùng khớp.

Lưu ý riêng cho `services/frontend/`: static UI (chat + Approve/Reject HITL), SSE qua `fetch + ReadableStream`
vì cần POST + Authorization header (không dùng EventSource), `API_BASE_URL` inject runtime qua `envsubst`.
Văn bản hiển thị tiếng Việt.