from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

from HEAL.tools.reliability.taxonomy import ReliabilityIssue, Severity, FailureType, AgentStage

_PATIENT_GRAIN = re.compile(
    r"\b(one\s+row\s+per\s+patient|per\s+patient|distinct\s+patients?|patient[- ]level|"
    r"each\s+patient|list\s+patients?)\b",
    re.I,
)
_POPULATION_GRAIN = re.compile(
    r"\b(population|monthly|per\s+month|by\s+month|DATE_TRUNC|time\s+bucket|scalar)\b",
    re.I,
)
_VISIT_ANCHOR = re.compile(r"\b(visit_date|encounter\s+date)\b", re.I)
_MEASURE_ANCHOR = re.compile(r"\b(recorded_date|test_date|measurement\s+date)\b", re.I)
_TABLE_REF = re.compile(r"\b([a-z][a-z0-9_]{2,})\b", re.I)
_DOMAIN_LAB = re.compile(r"\b(hba1c|glucose|creatinine|hemoglobin|ferritin|ldl|cholesterol)\b", re.I)


def _grain_label(text: str) -> str:
    if _PATIENT_GRAIN.search(text or ""):
        return "patient"
    if _POPULATION_GRAIN.search(text or ""):
        return "population"
    return "unspecified"


def _temporal_label(text: str) -> str:
    v = bool(_VISIT_ANCHOR.search(text or ""))
    m = bool(_MEASURE_ANCHOR.search(text or ""))
    if v and not m:
        return "visit"
    if m and not v:
        return "measurement"
    if v and m:
        return "mixed"
    return "unspecified"


def _tables_mentioned(text: str, known_tables: Set[str]) -> Set[str]:
    found: Set[str] = set()
    for tok in _TABLE_REF.findall(text or ""):
        t = tok.lower()
        if t in known_tables:
            found.add(t)
    return found


def _domain_tokens(text: str) -> Set[str]:
    return {m.group(0).lower() for m in _DOMAIN_LAB.finditer(text or "")}


def compute_disagreement_matrix(
    contracts: Dict[str, str],
    known_tables: Set[str],
) -> Dict[str, float]:
    cip, at, nj = contracts.get("cip", ""), contracts.get("at", ""), contracts.get("nj", "")

    def _pair(a_text: str, b_text: str) -> float:
        score = 0.0
        ga, gb = _grain_label(a_text), _grain_label(b_text)
        if ga != "unspecified" and gb != "unspecified" and ga != gb:
            score += 0.45
        ta, tb = _temporal_label(a_text), _temporal_label(b_text)
        if ta != "unspecified" and tb != "unspecified" and ta != tb and "mixed" not in (ta, tb):
            score += 0.35
        da, db = _domain_tokens(a_text), _domain_tokens(b_text)
        if da and db and not da.intersection(db):
            score += 0.25
        ta_set = _tables_mentioned(a_text, known_tables)
        tb_set = _tables_mentioned(b_text, known_tables)
        if ta_set and tb_set:
            union = ta_set | tb_set
            inter = ta_set & tb_set
            jaccard = len(inter) / len(union) if union else 1.0
            score += (1.0 - jaccard) * 0.25
        return min(1.0, score)

    return {
        "cip_at": round(_pair(cip, at), 3),
        "cip_nj": round(_pair(cip, nj), 3),
        "at_nj": round(_pair(at, nj), 3),
    }


def disagreement_issues(
    matrix: Dict[str, float],
    threshold: float = 0.35,
) -> List[ReliabilityIssue]:
    issues: List[ReliabilityIssue] = []
    labels = {
        "cip_at": ("CIP", "HEAL-AT"),
        "cip_nj": ("CIP", "HEAL-NJ"),
        "at_nj": ("HEAL-AT", "HEAL-NJ"),
    }
    for key, score in matrix.items():
        if score < threshold:
            continue
        a, b = labels.get(key, (key, ""))
        sev = Severity.CRITICAL.value if score >= 0.55 else Severity.WARNING.value
        issues.append(
            ReliabilityIssue(
                severity=sev,
                failure_type=FailureType.REASONING.value,
                source=AgentStage.CROSS.value,
                stage=AgentStage.CROSS.value,
                message=(
                    f"Agent disagreement ({a} vs {b}): score={score:.2f} — "
                    "grain, temporal anchor, domain, or join-table focus may diverge."
                ),
            )
        )
    return issues


def aggregate_disagreement(matrix: Dict[str, float]) -> float:
    if not matrix:
        return 0.0
    return min(1.0, sum(matrix.values()) / len(matrix))
