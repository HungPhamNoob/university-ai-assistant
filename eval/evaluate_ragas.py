"""Evaluate the live UET RAG pipeline with a source-derived RAGAS dataset.

The script retrieves real Qdrant contexts, generates a grounded answer from
those contexts, then measures answer faithfulness/relevancy and context
precision/recall. Generated CSV/Markdown reports stay local via .gitignore.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import sys
import types
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv

# ragas 0.4 imports a module removed by newer langchain-community releases.
if "langchain_community.chat_models.vertexai" not in sys.modules:
    try:
        import langchain_community.chat_models.vertexai  # noqa: F401
    except ImportError:
        vertex_stub = types.ModuleType("langchain_community.chat_models.vertexai")
        vertex_stub.ChatVertexAI = type("ChatVertexAI", (), {})
        sys.modules["langchain_community.chat_models.vertexai"] = vertex_stub
        import langchain_community.llms as community_llms

        if not hasattr(community_llms, "VertexAI"):
            community_llms.VertexAI = type("VertexAI", (), {})

from datasets import Dataset
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import (
    AnswerRelevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from ragas.run_config import RunConfig

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "eval" / "test_dataset.json"
CSV_PATH = ROOT / "eval" / "ragas_results.csv"
SUMMARY_PATH = ROOT / "eval" / "ragas_results.md"
RESCORE_PARTIAL_PATH = ROOT / "eval" / "ragas_rescore_partial.csv"
METRIC_NAMES = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
]

load_dotenv(ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


def rag_search_url() -> str:
    """Normalize either a service root URL or a full search endpoint."""
    configured = os.getenv("RAG_SERVICE_URL", "http://localhost:8002").rstrip("/")
    if configured.endswith("/api/kb/search"):
        return configured
    return f"{configured}/api/kb/search"


def load_records() -> list[dict[str, str]]:
    """Load and optionally limit the source-derived evaluation records."""
    records = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    limit = int(os.getenv("RAGAS_LIMIT", "0"))
    if limit > 0:
        return records[:limit]
    return records


def retrieve_contexts(client: httpx.Client, question: str) -> list[str]:
    """Retrieve real contexts from the running RAG service."""
    response = client.post(
        rag_search_url(),
        json={"query": question, "top_k": 5, "diversity": 0.7},
    )
    response.raise_for_status()
    payload = response.json()
    return [
        str(result["text"])
        for result in payload.get("results", [])
        if result.get("text")
    ]


def answer_from_contexts(
    llm: ChatOpenAI,
    question: str,
    contexts: list[str],
) -> str:
    """Generate one answer constrained to the retrieved UET passages."""
    if not contexts:
        return "The UET reference knowledge base did not provide relevant evidence."

    context_block = "\n\n---\n\n".join(contexts)
    system_text = (
        "Answer only from the supplied UET reference passages. Preserve whether "
        "a statement is official, public-source-grounded, illustrative, or a "
        "generated draft. If a requested field is absent, say it is absent. "
        "Do not add facts from memory."
    )
    user_text = f"Question:\n{question}\n\nReference passages:\n{context_block}"
    response = llm.invoke(
        [
            SystemMessage(content=system_text),
            HumanMessage(content=user_text),
        ]
    )
    return str(response.content)


def write_summary(results: pd.DataFrame) -> None:
    """Write compact overall and per-category metric summaries."""
    available_metrics = [name for name in METRIC_NAMES if name in results.columns]
    overall = results[available_metrics].mean(numeric_only=True)
    by_category = results.groupby("category")[available_metrics].mean(numeric_only=True)

    lines = [
        "# UET RAGAS results",
        "",
        f"Evaluated records: **{len(results)}**",
        "",
        "## Overall",
        "",
        "| Metric | Score |",
        "|---|---:|",
    ]
    for metric, score in overall.items():
        lines.append(f"| {metric} | {score:.4f} |")

    lines.extend(["", "## By category", "", by_category.to_markdown()])
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_chat_model() -> ChatOpenAI:
    """Single LLM factory shared by grounded answering and the RAGAS judge.

    max_retries=5 lets the OpenAI client ride out brief provider or local
    network drops instead of turning them into permanently unscored rows.
    """
    return ChatOpenAI(
        model=os.environ["LLM_MODEL"],
        api_key=os.environ["API_KEY"],
        base_url=os.environ["BASE_URL"],
        temperature=0.0,
        timeout=180,
        max_retries=5,
    )


def build_run_config() -> RunConfig:
    """Retry-friendly executor config for the RAGAS judge jobs."""
    return RunConfig(
        timeout=int(os.getenv("RAGAS_TIMEOUT_SECONDS", "900")),
        max_workers=int(os.getenv("RAGAS_MAX_WORKERS", "4")),
        max_retries=10,
        max_wait=120,
    )


def rows_missing_metrics(frame: pd.DataFrame) -> list[int]:
    """Return indices of rows whose metric cells are blank or NaN."""
    missing = []
    for position in range(len(frame)):
        row = frame.iloc[position]
        if any(
            pd.isna(row[name]) or str(row[name]).strip() == "" for name in METRIC_NAMES
        ):
            missing.append(position)
    return missing


def load_rescore_checkpoint(expected_rows: int) -> pd.DataFrame | None:
    """Return cached judge results when they match the current missing rows."""
    if not RESCORE_PARTIAL_PATH.exists():
        return None
    cached = pd.read_csv(RESCORE_PARTIAL_PATH)
    if len(cached) != expected_rows:
        logger.info(
            "Ignoring stale rescore checkpoint (%d rows, expected %d)",
            len(cached),
            expected_rows,
        )
        return None
    logger.info(
        "Reusing rescore checkpoint with %d rows from %s",
        len(cached),
        RESCORE_PARTIAL_PATH,
    )
    return cached


def rescore_missing_metrics() -> int:
    """Re-judge only the rows whose scoring failed in a previous run.

    Contexts and answers are reused from eval/ragas_results.csv, so this mode
    needs only the judge LLM: no RAG service, no answer regeneration. Enable
    with RAGAS_RESCORE=1 after a run whose metrics were cut short by network
    or provider errors.

    Judge results are checkpointed to eval/ragas_rescore_partial.csv before
    merging, so a crashed merge resumes without paying for the judge calls
    again; the checkpoint is deleted after a successful merge.
    """
    if not CSV_PATH.exists():
        logger.error("No %s to rescore; run the full evaluation first.", CSV_PATH)
        return 1

    previous = pd.read_csv(CSV_PATH)
    missing = rows_missing_metrics(previous)
    if not missing:
        logger.info("All %d rows are fully scored; nothing to rescore.", len(previous))
        return 0
    logger.info(
        "Rescoring %d/%d rows with missing metrics: %s",
        len(missing),
        len(previous),
        missing,
    )

    rescored = load_rescore_checkpoint(len(missing))
    if rescored is None:
        subset = previous.iloc[missing]
        dataset = Dataset.from_dict(
            {
                "question": subset["user_input"].tolist(),
                "ground_truth": subset["reference"].tolist(),
                "answer": subset["response"].tolist(),
                "contexts": [
                    ast.literal_eval(str(raw)) for raw in subset["retrieved_contexts"]
                ],
            }
        )
        rescored = evaluate(
            dataset,
            metrics=[
                faithfulness,
                AnswerRelevancy(strictness=1),
                context_precision,
                context_recall,
            ],
            llm=LangchainLLMWrapper(build_chat_model()),
            embeddings=LangchainEmbeddingsWrapper(
                HuggingFaceEmbeddings(
                    model_name=os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
                )
            ),
            run_config=build_run_config(),
        ).to_pandas()
        # Checkpoint before merging: expensive judge results are never lost,
        # even if a later step crashes.
        rescored.to_csv(RESCORE_PARTIAL_PATH, index=False)
        logger.info("Checkpointed judge results to %s", RESCORE_PARTIAL_PATH)

    for name in METRIC_NAMES:
        if name in rescored.columns:
            previous.loc[missing, name] = rescored[name].to_numpy()

    previous.to_csv(CSV_PATH, index=False)
    write_summary(previous)
    RESCORE_PARTIAL_PATH.unlink(missing_ok=True)

    still_missing = rows_missing_metrics(pd.read_csv(CSV_PATH))
    logger.info(
        "Saved %s and %s; rows still missing metrics: %s",
        CSV_PATH,
        SUMMARY_PATH,
        still_missing or "none",
    )
    return 0


def main() -> int:
    """Run retrieval, grounded generation and RAGAS scoring."""
    records = load_records()
    logger.info("Loaded %d UET evaluation records", len(records))

    answer_llm = build_chat_model()

    answers: list[str] = []
    contexts_per_question: list[list[str]] = []
    with httpx.Client(timeout=180.0) as client:
        for index, record in enumerate(records, start=1):
            question = record["question"]
            logger.info("[%d/%d] %s", index, len(records), question)
            contexts = retrieve_contexts(client, question)
            answer = answer_from_contexts(answer_llm, question, contexts)
            contexts_per_question.append(contexts)
            answers.append(answer)

    dataset = Dataset.from_dict(
        {
            "question": [record["question"] for record in records],
            "ground_truth": [record["ground_truth"] for record in records],
            "answer": answers,
            "contexts": contexts_per_question,
        }
    )

    judge_llm = LangchainLLMWrapper(answer_llm)
    judge_embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(
            model_name=os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
        )
    )
    results = evaluate(
        dataset,
        metrics=[
            faithfulness,
            AnswerRelevancy(strictness=1),
            context_precision,
            context_recall,
        ],
        llm=judge_llm,
        embeddings=judge_embeddings,
        run_config=build_run_config(),
    ).to_pandas()

    results.insert(1, "category", [record["category"] for record in records])
    results.to_csv(CSV_PATH, index=False)
    write_summary(results)
    logger.info("Saved %s and %s", CSV_PATH, SUMMARY_PATH)
    return 0


if __name__ == "__main__":
    if os.getenv("RAGAS_RESCORE", "0") == "1":
        raise SystemExit(rescore_missing_metrics())
    raise SystemExit(main())
