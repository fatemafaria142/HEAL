from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_INPUT = ROOT / "output" / "run_results.json"
DEFAULT_OUTPUT = ROOT / "output" / "cost_metrics" / "summary.json"


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("items") or []


def compute_cost_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}

    total_cost = 0.0
    total_tokens = 0
    total_input = 0
    total_output = 0
    wall_clocks: List[float] = []
    by_agent: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {
            "queries": 0,
            "llm_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "latency_ms": 0.0,
        }
    )
    model = None
    pricing = None

    for row in rows:
        rep = row.get("cost_report") or {}
        if not rep:
            continue
        model = rep.get("model") or model
        pricing = rep.get("pricing_per_1m_tokens_usd") or pricing
        total_cost += float(rep.get("total_cost_usd") or 0)
        total_tokens += int(rep.get("total_tokens") or 0)
        total_input += int(rep.get("total_input_tokens") or 0)
        total_output += int(rep.get("total_output_tokens") or 0)
        wall_clocks.append(float(rep.get("wall_clock_ms") or 0))
        for agent_id, stats in (rep.get("by_agent") or {}).items():
            b = by_agent[agent_id]
            b["queries"] += 1
            b["llm_calls"] += int(stats.get("llm_calls") or 0)
            b["input_tokens"] += int(stats.get("input_tokens") or 0)
            b["output_tokens"] += int(stats.get("output_tokens") or 0)
            b["cost_usd"] += float(stats.get("cost_usd") or 0)
            b["latency_ms"] += float(stats.get("latency_ms") or 0)

    def _mean(xs: List[float]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    agent_summary = {}
    for aid, stats in sorted(by_agent.items()):
        q = max(stats["queries"], 1)
        agent_summary[aid] = {
            "mean_cost_usd_per_query": round(stats["cost_usd"] / q, 6),
            "mean_input_tokens_per_query": round(stats["input_tokens"] / q, 1),
            "mean_output_tokens_per_query": round(stats["output_tokens"] / q, 1),
            "mean_latency_ms_per_query": round(stats["latency_ms"] / q, 2),
            "total_cost_usd": round(stats["cost_usd"], 6),
            "total_llm_calls": int(stats["llm_calls"]),
        }

    with_cost = sum(1 for r in rows if r.get("cost_report"))
    return {
        "n_queries": n,
        "n_with_cost_report": with_cost,
        "model": model,
        "pricing_per_1m_tokens_usd": pricing,
        "mean_cost_usd_per_query": round(total_cost / max(with_cost, 1), 6),
        "mean_tokens_per_query": round(total_tokens / max(with_cost, 1), 1),
        "mean_input_tokens_per_query": round(total_input / max(with_cost, 1), 1),
        "mean_output_tokens_per_query": round(total_output / max(with_cost, 1), 1),
        "mean_wall_clock_ms": _mean(wall_clocks),
        "total_cost_usd": round(total_cost, 4),
        "by_agent": agent_summary,
        "metrics_for_paper": {
            "MCQ": round(total_cost / max(with_cost, 1), 6),
            "MTQ": round(total_tokens / max(with_cost, 1), 1),
            "MWC": _mean(wall_clocks),
        },
    }


def run(input_path: Path | str | None = None, output_path: Path | str | None = None) -> Dict[str, Any]:
    input_path = Path(input_path or DEFAULT_INPUT)
    output_path = Path(output_path or DEFAULT_OUTPUT)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        print(f"Missing {input_path}. Run test/run_generate.py first.")
        return {}

    rows = _load_rows(input_path)
    summary = compute_cost_summary(rows)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary.get("metrics_for_paper", {}), indent=2))
    print(f"Wrote {output_path}")
    return summary


if __name__ == "__main__":
    run()
