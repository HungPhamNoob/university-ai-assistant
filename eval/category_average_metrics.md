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
