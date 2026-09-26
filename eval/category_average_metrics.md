# RAGAS category average metrics

Nguồn: `eval/ragas_results.csv` — full run **36/36** test cases của
`eval/test_dataset.json` (không đặt `RAGAS_LIMIT`), ngày 26-09-2026.
Context thật từ RAG service (Qdrant Cloud `uet_hr_docs`, 655 points);
LLM-judge qua provider trong `.env`.

`Scored` = số bản ghi tính được ít nhất một metric; các ô `—` là metric
không áp dụng được (xem Ghi chú).

## Overall

| Metric | Score |
|---|---:|
| faithfulness | 0.9195 |
| answer_relevancy | 0.7744 |
| context_precision | 0.6626 |
| context_recall | 0.4833 |

## By category

| Category | Records | Scored | faithfulness | answer_relevancy | context_precision | context_recall |
|:---|---:|---:|---:|---:|---:|---:|
| Analytical | 4 | 2 | 1.0000 | 0.0000 | 1.0000 | 0.2500 |
| Factual | 16 | 10 | 0.9083 | 0.8822 | 0.6895 | 0.7167 |
| Multi-hop | 7 | 4 | 0.8393 | 0.7536 | 0.5639 | 0.5000 |
| Negative | 1 | 0 | — | — | — | — |
| Relational | 8 | 5 | 0.9714 | 0.8850 | 0.5323 | 0.0000 |

## Ghi chú

- **Negative (1 bản ghi, không tính được metric — đúng thiết kế):** ca chống
  bịa đặt "GD3-402 có địa chỉ đường phố chính xác là gì?". Câu trả lời từ chối
  đúng ("trường này không có trong tài liệu"), nên không có claim nào để
  RAGAS chấm faithfulness và không có ground-truth context để chấm recall.
  Kết quả quan trọng nằm ở chính câu trả lời, không phải ở điểm số.
- **Các bản ghi không có điểm (Records − Scored):** judge không trích được
  statement nào để chấm (ví dụ câu trả lời trung thực "tài liệu không đủ để
  kết luận"), metric trả về rỗng/NaN và bị loại khỏi trung bình.
- **Analytical answer_relevancy = 0.0000 (2 bản ghi có điểm):** một câu trả
  lời dạng "tài liệu chỉ nói X, không giải thích vì sao" — trung thực nhưng
  không trả lời trực tiếp câu "tại sao", nên judge chấm 0; bản ghi còn lại
  trả lời đúng trọng tâm và 0.0 nhiều khả năng là artifact của judge. Đọc
  kèm câu trả lời trong `eval/ragas_results.csv` trước khi kết luận.
- **Relational context_recall = 0.0000:** câu hỏi về phạm vi/bằng chứng của
  khung AI trải trên nhiều mục tài liệu; retrieval top-5 không phủ được các
  đoạn mà ground truth tham chiếu, dù faithfulness vẫn cao (0.9714 — trả lời
  bám sát context lấy được, không bịa).
- **Overall answer_relevancy (0.7744)** bị kéo xuống chủ yếu bởi hai điểm 0
  của Analytical; các category còn lại đạt 0.75–0.89.
- Muốn có số mới: chạy `uv run python eval/evaluate_ragas.py` (stack phải
  đang bật qua `bash scripts/local.sh`) rồi tạo lại bảng này từ
  `eval/ragas_results.csv`.
