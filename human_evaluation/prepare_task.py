from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS = ROOT / "output" / "llm_judge_result" / "evaluation_summary.json"
DEFAULT_CSV = Path(__file__).resolve().parent / "human_annotation_task.csv"


def prepare_human_eval(
    eval_results_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> None:
    eval_results_path = Path(eval_results_path or DEFAULT_RESULTS)
    output_path = Path(output_path or DEFAULT_CSV)

    if not eval_results_path.is_file():
        print(f"Error: {eval_results_path} not found. Run automatic_evaluation/llm_judge.py first.")
        return

    with open(eval_results_path, encoding="utf-8") as f:
        data = json.load(f)

    rows_in = data.get("all_results") or data.get("details") or []
    annotation_rows = []

    for i, item in enumerate(rows_in):
        q = item.get("user_query") or item.get("question", "")
        g = item.get("ground_truth_sql") or item.get("gold_sql", "")
        p = item.get("generated_sql") or item.get("predicted_sql", "")
        annotation_rows.append(
            {
                "Item ID": i + 1,
                "Query ID": item.get("query_id", ""),
                "User Question": q,
                "Ground Truth SQL": g,
                "Generated SQL": p,
                "Human Label": "",
                "Score": "",
            }
        )

    df = pd.DataFrame(annotation_rows)
    df.to_csv(output_path, index=False)
    print(f"Human evaluation task written to {output_path}")
    print("Annotators: fill Human Label and Score (1–4).")


if __name__ == "__main__":
    prepare_human_eval()
