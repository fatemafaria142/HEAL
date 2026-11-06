from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

RUN_RESULTS = ROOT / "output" / "run_results.json"
JUDGE_DIR = ROOT / "output" / "llm_judge_result"
SUMMARY_FILE = JUDGE_DIR / "evaluation_summary.json"
METRICS_FILE = JUDGE_DIR / "metrics_snapshot.json"


class LLMSQLJudge:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.llm = ChatOpenAI(model=model_name, temperature=temperature)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an expert SQL auditor specialized in clinical databases. "
                    "Determine if generated SQL is semantically equivalent to ground truth SQL.",
                ),
                (
                    "user",
                    """User Question: {question}
Ground Truth SQL: {gold_sql}
Predicted SQL: {predicted_sql}

Compare Predicted SQL to Ground Truth in context of the question.
1. Assign score and label:
   - 4 (Fully Correct): Equivalent or logically identical.
   - 3 (Mostly Correct): Minor differences; likely same results for intent.
   - 2 (Partially Correct): Partial logic; would often return wrong results.
   - 1 (Fully Incorrect): Wrong tables, filters, or logic.

Return ONLY JSON:
{{
  "equivalent": bool,
  "score": int,
  "label": "string",
  "explanation": "string"
}}
""",
                ),
            ]
        )

    def judge(self, question: str, gold_sql: str, predicted_sql: str) -> dict:
        if not predicted_sql:
            return {
                "equivalent": False,
                "score": 1,
                "label": "Fully Incorrect",
                "explanation": "No SQL predicted.",
            }
        try:
            chain = self.prompt | self.llm
            response = chain.invoke(
                {
                    "question": question,
                    "gold_sql": gold_sql or "",
                    "predicted_sql": predicted_sql,
                }
            )
            content = (response.content or "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)
        except Exception as e:
            return {
                "equivalent": False,
                "score": 1,
                "label": "Fully Incorrect",
                "explanation": f"Judge error: {e}",
            }


def _load_run_results(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Run: python test/run_generate.py"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"meta": {}, "items": data}
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("run_results.json must be a list or {{ 'items': [...] }}")
    return {"meta": data.get("meta") or {}, "items": items}


def run_judge(
    run_results_path: Path | None = None,
    out_dir: Path | None = None,
) -> None:
    run_results_path = run_results_path or RUN_RESULTS
    out_dir = out_dir or JUDGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = _load_run_results(run_results_path)
    items = bundle["items"]
    judge = LLMSQLJudge()
    all_results = []

    for i, row in enumerate(items):
        qid = row.get("query_id", f"Q_{i+1:03d}")
        question = row.get("question", "")
        gold_sql = row.get("gold_sql", "")
        predicted_sql = row.get("predicted_sql") or ""
        judgement = judge.judge(question, gold_sql, predicted_sql)
        score = int(judgement.get("score", 1))
        label = judgement.get("label", "Fully Incorrect")
        all_results.append(
            {
                "query_id": qid,
                "user_query": question,
                "ground_truth_sql": gold_sql,
                "generated_sql": predicted_sql,
                "individual_score": score,
                "label": label,
                "explanation": judgement.get("explanation", ""),
                "equivalent": judgement.get("equivalent", False),
            }
        )

    n = len(all_results)
    avg = sum(r["individual_score"] for r in all_results) / n if n else 0.0
    label_dist: dict[str, int] = {}
    for r in all_results:
        label_dist[r["label"]] = label_dist.get(r["label"], 0) + 1

    summary = {
        "LLM_average_score_1_to_4": round(avg, 4),
        "total_samples": n,
        "label_distribution": label_dist,
        "source_run_results": str(run_results_path.resolve()),
        "judged_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    payload = {
        "summary": summary,
        "all_results": all_results,
    }
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    metrics_only = {
        "summary": summary,
        "meta": bundle.get("meta", {}),
    }
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(metrics_only, f, indent=2)

    print(f"Wrote {SUMMARY_FILE}")
    print(f"Wrote {METRICS_FILE}")
    print(f"Average score: {summary['LLM_average_score_1_to_4']} / 4.0 ({n} items)")


if __name__ == "__main__":
    run_judge()
