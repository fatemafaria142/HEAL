from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

DEFAULT_INPUT = ROOT / "output" / "llm_judge_result" / "evaluation_summary.json"
DEFAULT_OUTPUT = ROOT / "output" / "error_analysis" / "error_analysis_results.json"


class LLMErrorAnalyzer:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.llm = ChatOpenAI(model=model_name, temperature=temperature)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an expert SQL debugger for clinical relational schemas.",
                ),
                (
                    "user",
                    """User Question: {question}
Ground Truth SQL: {gold_sql}
Predicted SQL: {predicted_sql}
System Error (if any): {error}

Taxonomy (pick ONE primary category):
1. Wrong JOIN — wrong table links, missing joins, wrong grain.
2. Incorrect Filter — wrong WHERE, constants, or column in filter.
3. Aggregation Error — GROUP BY, COUNT/SUM/AVG misuse.
4. Syntax Error — invalid SQL / parse failure.
5. Schema Misalignment — wrong/missing tables or columns for the schema.

Return ONLY JSON:
{{
  "category": "Wrong JOIN" | "Incorrect Filter" | "Aggregation Error" | "Syntax Error" | "Schema Misalignment",
  "explanation": "string"
}}
""",
                ),
            ]
        )

    def analyze(self, item: Dict[str, Any]) -> Dict[str, Any]:
        try:
            chain = self.prompt | self.llm
            response = chain.invoke(
                {
                    "question": item.get("question") or "",
                    "gold_sql": item.get("gold_sql") or "",
                    "predicted_sql": item.get("predicted_sql") or "",
                    "error": item.get("error") or "None",
                }
            )
            content = (response.content or "").strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)
        except Exception as e:
            return {"category": "Unknown", "explanation": str(e)}


def perform_error_analysis(
    results_json_path: Path | str | None = None,
    output_path: Path | str | None = None,
) -> List[Dict[str, Any]]:
    results_json_path = Path(results_json_path or DEFAULT_INPUT)
    output_path = Path(output_path or DEFAULT_OUTPUT)

    if not results_json_path.is_file():
        print(f"Missing input: {results_json_path}. Run automatic_evaluation/llm_judge.py first.")
        return []

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(results_json_path, encoding="utf-8") as f:
        data = json.load(f)

    details: List[Dict[str, Any]] = data.get("all_results") or data.get("details") or []
    failed = [x for x in details if int(x.get("individual_score", 4)) < 4]

    if not failed:
        print("No imperfect cases (score < 4); writing empty list.")
        out: List[Dict[str, Any]] = []
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Wrote {output_path}")
        return out

    analyzer = LLMErrorAnalyzer()
    error_rows = []
    for i, item in enumerate(failed):
        processed = {
            "question": item.get("user_query") or item.get("question"),
            "gold_sql": item.get("ground_truth_sql") or item.get("gold_sql"),
            "predicted_sql": item.get("generated_sql") or item.get("predicted_sql"),
            "error": item.get("error", "None"),
        }
        print(f"  [{i + 1}/{len(failed)}] {str(processed['question'])[:60]}...")
        tax = analyzer.analyze(processed)
        error_rows.append(
            {
                "query_id": item.get("query_id", f"Q_{i + 1}"),
                "question": processed["question"],
                "gold_sql": processed["gold_sql"],
                "predicted_sql": processed["predicted_sql"],
                "individual_score": item.get("individual_score"),
                "error_taxonomy": tax,
            }
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(error_rows, f, indent=2)

    counts: Dict[str, int] = {}
    for r in error_rows:
        cat = r["error_taxonomy"].get("category", "Unknown")
        counts[cat] = counts.get(cat, 0) + 1
    print("\n--- Error taxonomy counts ---")
    for cat, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {c}")
    print(f"\nWrote {output_path}")
    return error_rows


if __name__ == "__main__":
    perform_error_analysis()
