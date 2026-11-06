from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from HEAL.core.orchestrator import HEALOrchestrator
from HEAL.tools.guards.contract_guard import parse_schema_catalog
from HEAL.tools.reliability.sql_hallucination import ground_sql_in_schema
import config

TEST_JSON = ROOT / "test" / "test_queries.json"
RUN_RESULTS = ROOT / "output" / "run_results.json"
SINGLE_RUN_DIR = ROOT / "output" / "single_runs"


def _load_json(path: Path) -> list:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise ValueError(f"{path} must be a JSON list or {{ 'items': [...] }}")


def _index_by_query_id(rows: list) -> dict:
    out = {}
    for r in rows:
        qid = r.get("query_id")
        if qid is not None:
            out[str(qid)] = r
    return out


def _build_item(
    qid: str,
    question: str,
    gold_sql: str,
    reasoning_type: Optional[str],
    state: Dict[str, Any],
    tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
) -> Dict[str, Any]:
    sql = state.get("sql") or ""
    results = state.get("results") or []
    grounding = ground_sql_in_schema(sql, tables, columns_by_table) if sql else None
    return {
        "query_id": qid,
        "question": question,
        "gold_sql": gold_sql,
        "reasoning_type": reasoning_type,
        "predicted_sql": sql,
        "response": (state.get("response") or "").strip(),
        "error": state.get("error"),
        "results_count": len(results) if isinstance(results, list) else 0,
        "contract_valid": state.get("contract_valid"),
        "contract_uncertainty": state.get("contract_uncertainty"),
        "contract_repair_count": state.get("contract_repair_count", 0),
        "disagreement_matrix": state.get("disagreement_matrix"),
        "reliability_report": state.get("reliability_report"),
        "reliability_snapshots": state.get("reliability_snapshots"),
        "cost_report": state.get("cost_report"),
        "schema_grounding": grounding.to_dict() if grounding else None,
        "resumed": False,
    }


def _build_error_item(
    qid: str, question: str, gold_sql: str, reasoning_type: Optional[str], exc: Exception
) -> Dict[str, Any]:
    return {
        "query_id": qid,
        "question": question,
        "gold_sql": gold_sql,
        "reasoning_type": reasoning_type,
        "predicted_sql": "",
        "response": "",
        "error": str(exc),
        "results_count": 0,
        "schema_grounding": None,
        "resumed": False,
    }


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def run_batch(*, resume: bool = False, input_path: Optional[str] = None) -> Path:
    RUN_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    test_file = Path(input_path) if input_path else TEST_JSON

    cases = _load_json(test_file)
    prior: dict = {}
    if resume and RUN_RESULTS.is_file():
        prior = _index_by_query_id(_load_json(RUN_RESULTS))

    orch = HEALOrchestrator()
    tables, columns_by_table = parse_schema_catalog(orch.schema_summary)
    items: list = []

    def save() -> Dict[str, Any]:
        bundle = {
            "meta": {
                "generated_by": "test/run_generate.py",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "test_file": str(test_file.resolve()),
                "resume": resume,
                "openai_model": config.OPENAI_MODEL,
                "schema_summary": orch.schema_summary,
            },
            "items": items,
        }
        _atomic_write(RUN_RESULTS, bundle)
        return bundle

    for i, row in enumerate(cases):
        qid = str(row.get("query_id", f"Q_{i + 1:03d}"))
        question = row.get("question", "").strip()
        gold_sql = row.get("gold_sql", "")
        reasoning_type = row.get("reasoning_type")

        if resume and qid in prior:
            old = prior[qid]
            if old.get("predicted_sql") and not row.get("force_regenerate"):
                items.append({**old, "resumed": True})
                print(f"[resume] {qid} — kept existing result")
                continue

        print(f"[{i + 1}/{len(cases)}] {qid}: {question[:70]}...")
        try:
            state = orch.process_query(question)
            items.append(_build_item(qid, question, gold_sql, reasoning_type, state, tables, columns_by_table))
        except Exception as e:
            items.append(_build_error_item(qid, question, gold_sql, reasoning_type, e))

        save()

    save()
    print(f"\nWrote {RUN_RESULTS} ({len(items)} items)")
    return RUN_RESULTS


def run_single(question: str, *, gold_sql: str = "", query_id: str = "AD_HOC") -> Path:
    orch = HEALOrchestrator()
    tables, columns_by_table = parse_schema_catalog(orch.schema_summary)

    print(f"Running: {question}")
    try:
        state = orch.process_query(question)
        item = _build_item(query_id, question, gold_sql, None, state, tables, columns_by_table)
    except Exception as e:
        item = _build_error_item(query_id, question, gold_sql, None, e)

    SINGLE_RUN_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = SINGLE_RUN_DIR / f"{ts}_{query_id}.json"
    bundle = {
        "meta": {
            "generated_by": "test/run_generate.py --query",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "openai_model": config.OPENAI_MODEL,
            "schema_summary": orch.schema_summary,
        },
        "items": [item],
    }
    _atomic_write(out_path, bundle)

    grounding = item.get("schema_grounding") or {}
    print(f"\nSQL     : {item['predicted_sql'] or '(none — pipeline stopped before SQL)'}")
    if item.get("error"):
        print(f"Error   : {item['error']}")
    if item["predicted_sql"]:
        print(f"Hallucinated (schema-grounded): {grounding.get('hallucinated')}")
        if grounding.get("unknown_tables"):
            print(f"  unknown tables : {grounding['unknown_tables']}")
        if grounding.get("unknown_columns"):
            print(f"  unknown columns: {grounding['unknown_columns']}")
    print(f"CAV+ uncertainty (MUS): {item.get('contract_uncertainty')}")
    print(f"Wrote {out_path}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description="Run HEAL in batch or single-query mode.")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Reuse the full prior result (incl. metrics) from output/run_results.json when query_id matches",
    )
    p.add_argument(
        "--input",
        default=None,
        help="Queries JSON to use instead of test/test_queries.json (batch mode only)",
    )
    p.add_argument(
        "--query",
        default=None,
        help="Run one ad hoc question instead of the batch file; saved under output/single_runs/",
    )
    p.add_argument("--gold-sql", default="", help="Optional gold SQL to attach when using --query")
    p.add_argument("--query-id", default="AD_HOC", help="Label for the ad hoc query result file")
    args = p.parse_args()

    if args.query:
        run_single(args.query, gold_sql=args.gold_sql, query_id=args.query_id)
    else:
        run_batch(resume=args.resume, input_path=args.input)


if __name__ == "__main__":
    main()
