from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from HEAL.tools.guards.contract_guard import parse_schema_catalog
from HEAL.tools.reliability.sql_hallucination import ground_sql_in_schema

DEFAULT_INPUT = ROOT / "output" / "run_results.json"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "hallucination_metrics"




def _confusion(y_true: Sequence[int], y_pred: Sequence[int]) -> Dict[str, int]:
    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _detection_scores(cm: Dict[str, int]) -> Dict[str, float]:
    tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
    n = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    accuracy = (tp + tn) / n if n else 0.0
    balanced = (recall + specificity) / 2

    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    mcc = ((tp * tn) - (fp * fn)) / denom if denom else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "specificity": round(specificity, 4),
        "balanced_accuracy": round(balanced, 4),
        "mcc": round(mcc, 4),
    }


def _auroc(scores: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    rank_sum_pos = sum(r for r, lbl in zip(ranks, labels) if lbl == 1)
    return round((rank_sum_pos - pos * (pos + 1) / 2) / (pos * neg), 4)


def _brier(scores: Sequence[float], labels: Sequence[int]) -> float:
    if not scores:
        return 0.0
    return round(sum((s - l) ** 2 for s, l in zip(scores, labels)) / len(scores), 4)


def _reliability_bins(
    scores: Sequence[float], labels: Sequence[int], n_bins: int = 10
) -> List[Dict[str, Any]]:
    bins: List[Dict[str, Any]] = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [
            i
            for i, s in enumerate(scores)
            if (s >= lo and s < hi) or (b == n_bins - 1 and s == 1.0)
        ]
        if not idx:
            bins.append({"bin": f"[{lo:.1f},{hi:.1f})", "n": 0, "mean_score": None, "observed_rate": None})
            continue
        mean_score = sum(scores[i] for i in idx) / len(idx)
        observed = sum(labels[i] for i in idx) / len(idx)
        bins.append(
            {
                "bin": f"[{lo:.1f},{hi:.1f})",
                "n": len(idx),
                "mean_score": round(mean_score, 4),
                "observed_rate": round(observed, 4),
                "gap": round(abs(mean_score - observed), 4),
            }
        )
    return bins


def _ece(scores: Sequence[float], labels: Sequence[int], n_bins: int = 10) -> float:
    if not scores:
        return 0.0
    total = len(scores)
    err = 0.0
    for b in _reliability_bins(scores, labels, n_bins):
        if not b["n"]:
            continue
        err += (b["n"] / total) * b["gap"]
    return round(err, 4)




def _load_bundle(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data, {}
    return (data.get("items") or data.get("results") or []), (data.get("meta") or {})


def _resolve_catalog(
    meta: Dict[str, Any], schema_file: Optional[Path]
) -> Tuple[Set[str], Dict[str, Set[str]]]:
    if meta.get("schema_summary"):
        return parse_schema_catalog(meta["schema_summary"])

    if schema_file and Path(schema_file).is_file():
        return parse_schema_catalog(Path(schema_file).read_text(encoding="utf-8"))

    try:
        from sqlalchemy import create_engine

        import config
        from database.schema_introspect import introspect_schema_markdown

        engine = create_engine(config.DATABASE_URL)
        return parse_schema_catalog(introspect_schema_markdown(engine))
    except Exception as e:
        raise SystemExit(
            "Could not resolve the schema catalogue. Re-run test/run_generate.py so the "
            "bundle stores `meta.schema_summary`, pass --schema-file, or make DATABASE_URL "
            f"reachable. Underlying error: {e}"
        )


def label_rows(
    rows: List[Dict[str, Any]],
    tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
    *,
    count_execution_error: bool = False,
) -> List[Dict[str, Any]]:
    labelled: List[Dict[str, Any]] = []

    for row in rows:
        rep = row.get("reliability_report") or {}
        sql = (row.get("predicted_sql") or "").strip()
        blocked = row.get("contract_valid") is False and not sql

        precomputed = row.get("schema_grounding")
        if precomputed is not None:
            grounding_dict = precomputed
            schema_hallucinated = bool(precomputed.get("hallucinated"))
        elif sql:
            grounding = ground_sql_in_schema(sql, tables, columns_by_table)
            grounding_dict = grounding.to_dict()
            schema_hallucinated = grounding.hallucinated
        else:
            grounding_dict = None
            schema_hallucinated = False

        truth: Optional[int]
        if blocked or not sql:
            truth = None
        else:
            truth = int(schema_hallucinated or (count_execution_error and bool(row.get("error"))))

        mus = float(
            rep.get("uncertainty_score")
            if rep.get("uncertainty_score") is not None
            else (row.get("contract_uncertainty") or 0.0)
        )

        labelled.append(
            {
                "query_id": row.get("query_id"),
                "question": row.get("question"),
                "reasoning_type": row.get("reasoning_type"),
                "predicted_sql": sql,
                "blocked_before_sql": blocked,
                "ground_truth_hallucination": truth,
                "heal_predicted_hallucination": int(bool(rep.get("hallucination_detected"))),
                "mus": mus,
                "mds": float(rep.get("disagreement_score") or 0.0),
                "prs": float(rep.get("propagation_risk") or 0.0),
                "execution_error": bool(row.get("error")),
                "schema_grounding": grounding_dict,
            }
        )
    return labelled




def compute_hallucination_metrics(labelled: List[Dict[str, Any]]) -> Dict[str, Any]:
    n_all = len(labelled)
    if not n_all:
        return {"n": 0, "message": "No rows"}

    verifiable = [r for r in labelled if r["ground_truth_hallucination"] is not None]
    blocked = [r for r in labelled if r["blocked_before_sql"]]

    y_true = [r["ground_truth_hallucination"] for r in verifiable]
    y_pred = [r["heal_predicted_hallucination"] for r in verifiable]
    mus = [r["mus"] for r in verifiable]

    cm = _confusion(y_true, y_pred)
    scores = _detection_scores(cm)

    n_ver = len(verifiable)
    n_hallu = sum(y_true)
    shr = round(n_hallu / n_ver, 4) if n_ver else 0.0

    identifier_counts = Counter()
    for r in verifiable:
        g = r.get("schema_grounding") or {}
        for t in g.get("unknown_tables") or []:
            identifier_counts[f"table:{t}"] += 1
        for c in g.get("unknown_columns") or []:
            identifier_counts[f"column:{c}"] += 1

    out: Dict[str, Any] = {
        "n_queries": n_all,
        "n_verifiable": n_ver,
        "blocked_unverifiable": {
            "count": len(blocked),
            "note": (
                "CAV+ blocked before SQL synthesis, so no SQL exists to ground-check. "
                "Excluded from detection scores to avoid circular credit; see PPR in "
                "reliability_metrics.py for the blocking rate itself."
            ),
        },
        "schema_hallucination_rate": shr,
        "n_hallucinated": n_hallu,
        "n_clean": n_ver - n_hallu,
        "confusion_matrix": cm,
        "detection_scores": scores,
        "uncertainty_as_predictor": {
            "auroc_mus": _auroc(mus, y_true),
            "brier_mus": _brier(mus, y_true),
            "ece_mus": _ece(mus, y_true),
            "reliability_bins": _reliability_bins(mus, y_true),
        },
        "most_hallucinated_identifiers": dict(identifier_counts.most_common(15)),
    }

    by_type: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in verifiable:
        if r.get("reasoning_type"):
            by_type[str(r["reasoning_type"])].append(r)

    if by_type:
        per_type = {}
        for rtype, group in sorted(by_type.items()):
            gt = [r["ground_truth_hallucination"] for r in group]
            gp = [r["heal_predicted_hallucination"] for r in group]
            gm = [r["mus"] for r in group]
            per_type[rtype] = {
                "n": len(group),
                "schema_hallucination_rate": round(sum(gt) / len(gt), 4),
                **_detection_scores(_confusion(gt, gp)),
                "ece_mus": _ece(gm, gt),
                "auroc_mus": _auroc(gm, gt),
            }
        eces = [v["ece_mus"] for v in per_type.values()]
        out["by_reasoning_type"] = per_type
        out["reasoning_ece"] = round(sum(eces) / len(eces), 4)

    out["metrics_for_paper"] = {
        "SHR": shr,
        "Precision": scores["precision"],
        "Recall": scores["recall"],
        "F1": scores["f1"],
        "Accuracy": scores["accuracy"],
        "BalancedAcc": scores["balanced_accuracy"],
        "MCC": scores["mcc"],
        "AUROC_MUS": out["uncertainty_as_predictor"]["auroc_mus"],
        "ECE_MUS": out["uncertainty_as_predictor"]["ece_mus"],
        "Brier_MUS": out["uncertainty_as_predictor"]["brier_mus"],
    }
    if "reasoning_ece" in out:
        out["metrics_for_paper"]["ReasoningECE"] = out["reasoning_ece"]

    return out


def run(
    input_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    *,
    schema_file: Path | str | None = None,
    count_execution_error: bool = False,
) -> Dict[str, Any]:
    input_path = Path(input_path or DEFAULT_INPUT)
    output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.is_file():
        print(f"Missing {input_path}. Run test/run_generate.py first.")
        return {}

    rows, meta = _load_bundle(input_path)
    tables, columns_by_table = _resolve_catalog(meta, Path(schema_file) if schema_file else None)

    labelled = label_rows(
        rows, tables, columns_by_table, count_execution_error=count_execution_error
    )
    summary = compute_hallucination_metrics(labelled)
    summary["ground_truth_definition"] = (
        "schema hallucination in executed SQL"
        + (" OR execution error" if count_execution_error else "")
    )

    with open(output_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    with open(output_dir / "per_query.json", "w", encoding="utf-8") as f:
        json.dump(labelled, f, indent=2)

    print(json.dumps(summary.get("metrics_for_paper", {}), indent=2))
    print(f"Wrote {output_dir / 'summary.json'}")
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--input", default=None, help="run_results.json (default: output/run_results.json)")
    p.add_argument("--output-dir", default=None)
    p.add_argument("--schema-file", default=None, help="Markdown schema dump, if the DB is unreachable")
    p.add_argument(
        "--count-execution-error",
        action="store_true",
        help="Also treat SQL that failed to execute as a hallucination",
    )
    a = p.parse_args()
    run(
        a.input,
        a.output_dir,
        schema_file=a.schema_file,
        count_execution_error=a.count_execution_error,
    )


if __name__ == "__main__":
    main()
