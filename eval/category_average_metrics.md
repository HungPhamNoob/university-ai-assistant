# RAGAS category average metrics

Nguồn: `eval/ragas_results.csv` (lượt chạy `RAGAS_LIMIT=6` ngày 26-09-2026,
context thật từ RAG service, LLM-judge qua provider trong `.env`).
Số bản ghi: **6**.

## Overall

| Metric | Score |
|---|---:|
| faithfulness | 0.8426 |
| answer_relevancy | 0.8097 |
| context_precision | 0.7093 |
| context_recall | 0.6111 |

## By category

| Category | Records | faithfulness | answer_relevancy | context_precision | context_recall |
|:---|---:|---:|---:|---:|---:|
| Factual | 3 | 0.7778 | 0.8349 | 0.9722 | 0.8889 |
| Multi-hop | 1 | 0.8333 | 0.9714 | 0.7556 | 1.0000 |
| Relational | 2 | 0.9444 | 0.6910 | 0.2917 | 0.0000 |

## Ghi chú

- Mẫu rất nhỏ (6 bản ghi, 1–3 mỗi category) vì chạy với `RAGAS_LIMIT=6`;
  các điểm trung bình theo category chỉ mang tính định hướng, không phải
  benchmark thống kê.
- Hai câu Relational hỏi về phạm vi đối tượng/hoạt động và bằng chứng cho
  quyết định AI rủi ro cao trong khung tham chiếu: `context_precision` và
  `context_recall` thấp cho thấy retrieval khó phủ đúng đoạn khi câu hỏi
  trải trên nhiều mục của tài liệu, dù `faithfulness` vẫn cao (câu trả lời
  không bịa ngoài context).
- Chạy lại toàn bộ 36 câu với `uv run python eval/evaluate_ragas.py`
  (không đặt `RAGAS_LIMIT`) để có số ổn định hơn, rồi tạo lại bảng này.
