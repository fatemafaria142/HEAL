from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_INPUT = ROOT / "output" / "run_results.json"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "reliability_metrics"


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("items") or data.get("results") or []


def compute_reliability_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "message": "No rows"}

    hallucination_flags = 0
    propagation_prevented = 0
    cav_pass = 0
    cav_block = 0
    repair_attempted = 0
    repair_ok = 0
    failure_types: Counter = Counter()
    failure_stages: Counter = Counter()
    uncertainty_vals: List[float] = []
    disagreement_vals: List[float] = []
    prs_vals: List[float] = []
    mitigations: Counter = Counter()
    disagreement_pairs: Dict[str, List[float]] = defaultdict(list)

    for row in rows:
        rep = row.get("reliability_report") or {}
        if rep.get("hallucination_detected"):
            hallucination_flags += 1
        if rep.get("propagation_prevented"):
            propagation_prevented += 1
        if rep.get("cav_passed", True):
            cav_pass += 1
        else:
            cav_block += 1
        if rep.get("repair_attempted"):
            repair_attempted += 1
        if rep.get("repair_succeeded"):
            repair_ok += 1
        ft = rep.get("primary_failure_type")
        if ft:
            failure_types[ft] += 1
        fs = rep.get("failure_stage")
        if fs:
            failure_stages[fs] += 1
        uncertainty_vals.append(float(rep.get("uncertainty_score") or row.get("contract_uncertainty") or 0))
        disagreement_vals.append(float(rep.get("disagreement_score") or 0))
        prs_vals.append(float(rep.get("propagation_risk") or 0))
        for m in rep.get("mitigations_applied") or []:
            mitigations[m] += 1
        for k, v in (rep.get("disagreement_matrix") or row.get("disagreement_matrix") or {}).items():
            disagreement_pairs[k].append(float(v))

    def _mean(xs: List[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    pair_means = {k: round(sum(v) / len(v), 4) for k, v in disagreement_pairs.items()}

    return {
        "n_queries": n,
        "hallucination_detection_rate": round(hallucination_flags / n, 4),
        "propagation_prevention_rate": round(propagation_prevented / n, 4),
        "cav_pass_rate": round(cav_pass / n, 4),
        "cav_block_rate": round(cav_block / n, 4),
        "contract_repair_attempt_rate": round(repair_attempted / n, 4),
        "contract_repair_success_rate": round(repair_ok / max(repair_attempted, 1), 4),
        "mean_uncertainty_score": _mean(uncertainty_vals),
        "mean_disagreement_score": _mean(disagreement_vals),
        "mean_propagation_risk_score": _mean(prs_vals),
        "failure_type_counts": dict(failure_types),
        "failure_stage_counts": dict(failure_stages),
        "mitigation_usage": dict(mitigations),
        "mean_disagreement_matrix": pair_means,
        "metrics_for_paper": {
            "HDR": round(hallucination_flags / n, 4),
            "PPR": round(propagation_prevented / n, 4),
            "CRS": round(repair_ok / max(repair_attempted, 1), 4),
            "MUS": _mean(uncertainty_vals),
            "MDS": _mean(disagreement_vals),
            "MPRS": _mean(prs_vals),
        },
    }


def run(
    input_path: Path | str | None = None,
    output_dir: Path | str | None = None,
) -> Dict[str, Any]:
    input_path = Path(input_path or DEFAULT_INPUT)
    output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        print(f"Missing {input_path}. Run test/run_generate.py first.")
        return {}

    rows = _load_rows(input_path)
    summary = compute_reliability_metrics(rows)

    out_main = output_dir / "summary.json"
    with open(out_main, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    by_type = {
        "failure_type_counts": summary.get("failure_type_counts", {}),
        "failure_stage_counts": summary.get("failure_stage_counts", {}),
        "mean_disagreement_matrix": summary.get("mean_disagreement_matrix", {}),
    }
    out_type = output_dir / "by_failure_type.json"
    with open(out_type, "w", encoding="utf-8") as f:
        json.dump(by_type, f, indent=2)

    print(json.dumps(summary.get("metrics_for_paper", {}), indent=2))
    print(f"Wrote {out_main}")
    return summary


if __name__ == "__main__":
    run()
