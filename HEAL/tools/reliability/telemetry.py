from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from HEAL.tools.reliability.taxonomy import ReliabilityIssue, primary_failure_type


@dataclass
class StageSnapshot:
    stage: str
    issue_count: int
    critical_count: int
    uncertainty: float
    disagreement: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReliabilityReport:
    hallucination_detected: bool = False
    primary_failure_type: Optional[str] = None
    failure_stage: Optional[str] = None
    issues: List[Dict[str, Any]] = field(default_factory=list)
    disagreement_matrix: Dict[str, float] = field(default_factory=dict)
    uncertainty_score: float = 0.0
    disagreement_score: float = 0.0
    propagation_risk: float = 0.0
    propagation_prevented: bool = False
    repair_attempted: bool = False
    repair_succeeded: bool = False
    cav_passed: bool = True
    cav_llm_verdict: Optional[str] = None
    self_verification: Dict[str, bool] = field(default_factory=dict)
    mitigations_applied: List[str] = field(default_factory=list)
    stage_snapshots: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_propagation_risk(
    issues: List[ReliabilityIssue],
    disagreement_score: float,
    stage: str = "pre_sql",
) -> float:
    if not issues:
        return round(disagreement_score * 0.4, 3)
    critical = sum(1 for i in issues if i.severity == "critical")
    warnings = len(issues) - critical
    base = min(1.0, critical * 0.35 + warnings * 0.12 + disagreement_score * 0.3)
    if stage == "post_cav_block":
        return round(min(1.0, base + 0.15), 3)
    return round(base, 3)


def build_report_from_issues(
    issues: List[ReliabilityIssue],
    *,
    disagreement_matrix: Dict[str, float],
    disagreement_score: float,
    uncertainty_score: float,
    cav_passed: bool = True,
    cav_llm_verdict: Optional[str] = None,
    self_verification: Optional[Dict[str, bool]] = None,
    mitigations: Optional[List[str]] = None,
    stage_snapshots: Optional[List[StageSnapshot]] = None,
    propagation_prevented: bool = False,
    repair_attempted: bool = False,
    repair_succeeded: bool = False,
    failure_stage: Optional[str] = None,
) -> ReliabilityReport:
    primary = primary_failure_type(issues)
    return ReliabilityReport(
        hallucination_detected=bool(issues) or not cav_passed,
        primary_failure_type=primary,
        failure_stage=failure_stage or ("cav" if not cav_passed else None),
        issues=[i.to_dict() for i in issues],
        disagreement_matrix=disagreement_matrix,
        uncertainty_score=round(uncertainty_score, 3),
        disagreement_score=round(disagreement_score, 3),
        propagation_risk=compute_propagation_risk(
            issues,
            disagreement_score,
            "post_cav_block" if propagation_prevented else "pre_sql",
        ),
        propagation_prevented=propagation_prevented,
        repair_attempted=repair_attempted,
        repair_succeeded=repair_succeeded,
        cav_passed=cav_passed,
        cav_llm_verdict=cav_llm_verdict,
        self_verification=self_verification or {},
        mitigations_applied=mitigations or [],
        stage_snapshots=[s.to_dict() for s in (stage_snapshots or [])],
    )