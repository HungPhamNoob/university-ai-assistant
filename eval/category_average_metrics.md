# RAGAS category average metrics

Nguồn: `eval/ragas_results.csv` — lượt chấm FULL 36/36 test cases của
`eval/test_dataset.json` ngày 26-09-2026 (context thật từ RAG service,
LLM-judge qua provider trong `.env`). Toàn bộ 144/144 ô metric đều chấm
được: lượt chạy đầu mất điểm 17 dòng do mạng đứt giữa chừng, đã phục hồi
bằng chế độ `RAGAS_RESCORE=1` (chấm lại đúng các ô trống, có checkpoint).

## Overall

| Metric | Score |
|---|---:|
| faithfulness | 0.8718 |
| answer_relevancy | 0.6810 |
| context_precision | 0.5954 |
| context_recall | 0.4074 |

## By category

| Category | Records | faithfulness | answer_relevancy | context_precision | context_recall |
|:---|---:|---:|---:|---:|---:|
| Analytical | 4 | 1.0000 | 0.2328 | 0.7375 | 0.2500 |
| Factual | 16 | 0.8922 | 0.7952 | 0.6066 | 0.6354 |
| Multi-hop | 7 | 0.7534 | 0.5709 | 0.4651 | 0.2857 |
| Negative | 1 | 0.3333 | 0.0000 | 1.0000 | 0.0000 |
| Relational | 8 | 0.9377 | 0.8581 | 0.5655 | 0.1875 |

## Ghi chú đọc bảng

- **Negative (1 bản ghi: f=0.33, ar=0, cp=1.00, cr=0)** là câu hỏi cố ý
  không có trong tài liệu (địa chỉ đường phố GD3-402). Hệ thống trả lời
  ĐÚNG kỳ vọng: "trường này không có trong nguồn". RAGAS phạt refusal về
  mặt cấu trúc: câu trả lời "không đáp ứng" bị tính relevancy = 0, và
  ground-truth dạng "không tồn tại" không thể đối chiếu về context nên
  recall = 0. Điểm thấp ở dòng này là artifact của metric, không phải lỗi
  chất lượng — đây chính là hành vi chống bịa đặt mong muốn.
- **Analytical (ar = 0.23)**: 3/4 câu là refusal đúng (tài liệu không
  chứa lời giải thích nhân quả, model từ chối suy diễn ngoài nguồn) và bị
  chấm relevancy = 0 như trên; câu còn lại được 0.93. faithfulness = 1.00
  tuyệt đối: không có phát minh nào ngoài bằng chứng.
- **Relational (cr = 0.19)**: các câu về phạm vi/bằng chứng của khung AI
  trải trên nhiều mục tài liệu; context_recall của RAGAS đối chiếu
  ground-truth theo câu chữ nên không gán được về đoạn retrieve, dù
  faithfulness 0.94 và relevancy 0.86 cho thấy câu trả lời bám sát
  context và đúng trọng tâm.
- **Multi-hop là nhóm yếu thật sự** (f=0.75, cp=0.47, cr=0.29): câu hỏi
  cần tổng hợp nhiều đoạn đang là điểm cải thiện retrieval rõ nhất.
- **Faithfulness toàn cục 0.87** (Factual 0.89, Relational 0.94,
  Analytical 1.00): câu trả lời gần như không bịa ngoài bằng chứng —
  metric quan trọng nhất với assistant chính sách nội bộ.
- Chạy lại: `uv run python eval/evaluate_ragas.py` (không đặt
  `RAGAS_LIMIT`); nếu mạng đứt giữa chừng thì chạy tiếp
  `RAGAS_RESCORE=1 uv run python eval/evaluate_ragas.py` để chấm bù đúng
  các ô trống, sau đó tạo lại bảng này từ `eval/ragas_results.csv`.
