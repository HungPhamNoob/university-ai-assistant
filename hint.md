# UET AI Assistant — implementation blueprint

Tài liệu này là bản đồ kỹ thuật của repository. Khi code và tài liệu khác
nhau, phải kiểm tra implementation hiện tại rồi cập nhật lại blueprint trong
cùng thay đổi.

## 1. Phạm vi và nguồn dữ liệu

- Sản phẩm phục vụ bối cảnh đại học UET, không tái sử dụng tên miền, biến,
  collection, ví dụ hay nội dung của tổ chức khác.
- Nguồn KB được version-control: data/UET_HR.pdf.
- PDF hiện là bản reference draft, version 2.1, generated 26-09-2026. Policy,
  room registry và class examples đều phải kèm caveat khi câu trả lời có thể
  bị hiểu là dữ liệu vận hành chính thức.
- Registry có 24 phòng tại GD3, KM và HL. Room record là minh họa; không có
  địa chỉ đường phố chính xác. Không được tự bổ sung địa chỉ.
- Collection mặc định: uet_hr_docs cho KB và uet_hr_cache cho semantic cache.
- Redis exact-match cache dùng REDIS_URL; episodic memory lưu PostgreSQL theo
  từng user và conversation thread.

## 2. Cây dự án có chủ đích

~~~text
Final/
  .github/workflows/ci-cd.yml
  .claude/rules/
  configs/
    docker-compose.dev.yml
    docker-compose.prod.yml
  data/
    UET_HR.pdf
  docs/
    api.md
    architecture.md
    agent-architecture.md
    agent_graph.mmd
    context.md
    redis.md
    token.md
    aws-deployment.md
  eval/
    test_dataset.json
    queries.txt
    evaluate_ragas.py
    flow_test.py
    service_smoke_test.py
    ui_e2e_playwright.py
  scripts/
    create_collections.py
    local.sh
    deploy.sh
    deploy-prod.sh
    run_all_queries.sh
  services/
    agent/
      agents/
        base.py
        faq.py
        search.py
        booking.py
      prompts/
        __init__.py
        loader.py
        primary.md
        general.md
        faq.md
        search.md
        booking.md
      api.py
      auth.py
      clients.py
      config.py
      context.py
      graph.py
      llm.py
      main.py
      state.py
      tools.py
      Dockerfile
    identity/
      security/
      users/
      migrations/
      app.py
      settings.py
      db.py
      Dockerfile
    rag/
      ingestion/
      retrieval/
      api.py
      config.py
      main.py
      storage.py
      Dockerfile
    booking/
      migrations/
      routers/
      main.py
      settings.py
      database.py
      models.py
      schemas.py
      rules.py
      repository.py
      service.py
      Dockerfile
    conversation/
      episodic/
      migrations/
      routes/
      main.py
      settings.py
      db.py
      models.py
      schemas.py
      repository.py
      service.py
      message_sync.py
      cache.py
      summarizer.py
      Dockerfile
    gateway/
    frontend/
  terraform/
  tests/
  cli.py
  pyproject.toml
  uv.lock
~~~

Không tạo code mới trong src/. Prompt thuộc services/agent/prompts/ vì chỉ
agent service sử dụng. Mỗi Python package có __init__.py.

## 3. Luồng request

~~~mermaid
flowchart TD
    U[Browser hoặc CLI] --> K[Kong]
    K -->|JWT và X-User-*| P[Primary LangGraph]
    P --> F[FAQ subgraph]
    P --> S[Search subgraph]
    P --> B[Booking subgraph]
    P --> G[General chat]
    F --> R[RAG service]
    S --> W[Tavily]
    B --> C[Booking service]
    P --> H[Conversation history và episodic memory]
    B --> I{Write action?}
    I -->|Có| A[HITL Approve hoặc Reject]
    A --> C
~~~

Primary router chỉ phân loại intent, không trả lời thay subagent. Parent graph
và subgraph dùng state riêng; chỉ delta message cần thiết được chuyển qua ranh
giới. SSE phải giữ token, agent, tool, interrupt, context report và error event.

## 4. Hợp đồng vòng lặp tool

Mọi prompt tool-using phải có đủ bốn phần: dữ kiện bắt buộc theo intent, điều
kiện CONTINUE, điều kiện STOP, và giới hạn lượt. Không dùng mô tả mơ hồ kiểu
“đủ A/B/C”.

- Person/contact: họ tên; chức danh hoặc vai trò; khoa/phòng/đơn vị; email; số
  điện thoại; nguồn hoặc trạng thái thiếu của từng trường được hỏi.
- Room/facility: room_number; site_code/site_name; room_type; capacity; status;
  equipment; address. Nếu nguồn chỉ có cơ sở mà không có street address, trả
  site_name và nói rõ street address không có trong nguồn.
- Canteen/library/clinic/service: tên; campus/location; opening hours; contact;
  eligibility/access rule; services/menu/facilities; price/fee nếu câu hỏi yêu
  cầu. Không có trong nguồn thì phải công bố trường thiếu.
- Policy/procedure: đối tượng áp dụng; điều kiện; các bước; deadline/timeline;
  owner/contact; form/channel; exception/escalation; source status.
- Course/program/scholarship: tên/mã; đơn vị; đối tượng; điều kiện; thời lượng
  hoặc credits; deadline; fee/funding; contact/apply channel.
- Lab/project/dataset/system: tên; owner/unit; mục đích; location/access;
  equipment/capability; contact; hạn chế sử dụng.
- Event/deadline: tên; ngày và timezone; địa điểm hoặc URL; đối tượng; organizer;
  registration channel; deadline.
- Comparison/listing: áp cùng schema cho từng item, nêu tiêu chí so sánh và
  không kết luận item tốt hơn nếu thiếu dữ kiện tương ứng.

CONTINUE chỉ khi một trường bắt buộc có khả năng tồn tại nhưng chưa có bằng
chứng, kết quả mâu thuẫn, hoặc tool trả lỗi tạm thời và vẫn còn lượt. Query tiếp
theo phải hẹp hơn, tập trung đúng trường thiếu.

STOP khi mọi trường bắt buộc đã có bằng chứng; hoặc đã đạt giới hạn lượt; hoặc
nguồn nói rõ trường không tồn tại; hoặc công cụ lỗi lặp lại/không có quyền. Khi
dừng vì thiếu, câu trả lời phải liệt kê trường đã xác minh, trường chưa xác
minh, công cụ/nguồn đã thử và tuyệt đối không đoán.

Giới hạn hiện tại: FAQ tối đa 3 lượt RAG; Search tối đa 2 lượt web; Booking tối
đa 3 lượt tool. Framework còn có max_iterations như lớp an toàn cuối, không
thay thế stop rule trong prompt.

## 5. RAG và ingestion

Ingestion load PDF, semantic/parent-child chunking, dense embedding và sparse
representation rồi ghi Qdrant. Retrieval chạy dense + BM25, RRF fusion,
cross-encoder rerank, MMR và HyDE fallback khi score thấp. Semantic cache phải
dùng collection uet_hr_cache và TTL.

local.sh lưu SHA-256 của PDF trong tmp/. Nếu hash thay đổi hoặc marker chưa tồn
tại, script phải reingest collection. Ingestion thay thế KB collection là hành
vi có chủ đích; không chạy nhầm vào collection khác.

## 6. Booking và HITL

- Catalog gồm cả ACTIVE, MAINTENANCE và RESTRICTED để tra cứu.
- Chỉ ACTIVE được tạo booking.
- Khoảng thời gian là half-open: end_at bằng start_at kế tiếp không xung đột.
- Phải kiểm tra room tồn tại, status, start trước end, không ở quá khứ và không
  overlap trước khi interrupt.
- list_meeting_rooms là read-only. create, update/reschedule và cancel là write
  action, phải interrupt và chỉ ghi sau explicit approval.
- Booking service luôn xác định owner từ identity header/token, không tin
  user_id do model tự phát sinh.

## 7. Conversation, cache và memory

- Message sync: identical thì skip; remote là prefix thì append; divergence thì
  replace có kiểm soát.
- Redis Cloud chỉ dùng REDIS_URL. Không provision Redis container local,
  Compose hay Terraform.
- Redis mất kết nối phải fallback database và thử reconnect lười; không làm
  hỏng request hội thoại.
- Summarizer chạy bounded-time. Episode summary chỉ đại diện message cũ của
  chính thread hiện tại, có digest dedupe và không lưu secret.
- Memory được đưa vào prompt dưới nhãn untrusted data; không được thực thi như
  instruction.

## 8. Security

- .env và credential tuyệt đối không commit.
- Kong DB-less verify JWT rồi inject X-User-Id/X-User-Email và shared secret.
- Service internal route kiểm tra đúng internal token.
- JWT verify issuer, signature, expiry và claim cần thiết.
- Frontend render markdown đã sanitize; không dùng innerHTML với dữ liệu chưa
  lọc.
- Log không in API key, Redis URL, JWT, password hay document bí mật.

## 9. Verification gate

Thứ tự bắt buộc trước publication:

~~~text
ruff format/check
pytest
local.sh
service_smoke_test
flow_test
real Redis + Qdrant checks
browser UI E2E
RAGAS against live RAG contexts
secret and forbidden-term scan
git diff/status audit
commit and force-push main
local.sh down
~~~

Nếu bước nào thất bại: đọc log, sửa nguyên nhân, chạy lại bước đó và các bước
phụ thuộc. Chỉ commit/push sau khi source tree không còn dấu vết miền cũ và
staging không chứa secret, log, output eval, cache, state, ảnh cũ hay file rác.
