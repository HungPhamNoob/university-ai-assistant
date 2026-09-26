# Coding principles — uet-hr-ai

> Luôn được load. Skill **`coding-simple`** (`.claude/skills/coding-simple/SKILL.md`) là chuẩn mặc định cho
> **mọi** công việc code trong repo này: viết code mới, refactor, review, sửa bug, viết test.
> Luôn load và tuân theo skill đó. Những điểm cốt lõi cần nhớ kể cả khi chưa load:

- **Ưu tiên: code rõ ràng > code ngắn > code khéo léo.** Mục tiêu không phải ít dòng code hơn.
- Viết code để một engineer mới vào team hiểu nhanh: control flow tường minh, guard clause,
  tên biến mô tả rõ, intermediate variable khi nó làm lộ các bước quan trọng.
- Tránh mặc định: nested ternary, one-liner nén, comprehension phức tạp,
  abstraction sớm, metaprogramming không lý do.
- **Giữ nguyên hành vi khi refactor** — input, output, side effect, error behavior, thứ tự thực thi.
  Không chắc thì không âm thầm đổi.
- **Phân loại mọi pattern quan trọng** khi đưa ra: industry-standard / big-tech-style / framework
  convention / project convention / custom choice. Không gắn nhãn "best practice" cho custom choice.
- Production quality không đồng nghĩa phức tạp tối đa: chọn architecture đơn giản nhất đáp ứng yêu
  cầu thật. Nhưng **không bao giờ** đơn giản hóa bỏ security, validation, transaction boundary,
  error handling cần thiết.
- Code "boring" là code production tốt. Chỉ sửa trong phạm vi task được yêu cầu.