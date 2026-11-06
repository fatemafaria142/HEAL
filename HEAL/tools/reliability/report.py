from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from HEAL.tools.guards.contract_guard import (
    ContractIssue,
    _collect_contract_text,
    _compute_uncertainty,
    parse_schema_catalog,
    run_deterministic_contract_checks,
)
from HEAL.tools.reliability.disagreement import aggregate_disagreement, compute_disagreement_matrix
from HEAL.tools.reliability.taxonomy import ReliabilityIssue, AgentStage
from HEAL.tools.reliability.telemetry import StageSnapshot, build_report_from_issues


def run_staged_checks(state: Dict[str, Any], stage: str) -> List[ReliabilityIssue]:
    contracts = _collect_contract_text(state)
    tables, _ = parse_schema_catalog(state.get("schema_summary") or "")
    issues: List[ReliabilityIssue] = []

    if stage == "post_cip":
        partial = run_deterministic_contract_checks({**state, "anjt_resolution": "", "join_nest_plan": ""})
        return [
            ReliabilityIssue(i.severity, i.failure_type, i.source, i.message, i.source)
            for i in partial.issues
            if i.source in ("cip", "cross")
        ]

    if stage == "post_at":
        partial = run_deterministic_contract_checks({**state, "join_nest_plan": ""})
        return [
            ReliabilityIssue(i.severity, i.failure_type, i.source, i.message, i.source)
            for i in partial.issues
            if i.source in ("at", "cross")
        ]

    if stage == "post_nj":
        partial = run_deterministic_contract_checks(state)
        return [
            ReliabilityIssue(i.severity, i.failure_type, i.source, i.message, i.source)
            for i in partial.issues
        ]

    return issues


def _stage_uncertainty(issues: List[ReliabilityIssue]) -> float:
    converted = [
        ContractIssue(i.severity, i.failure_type, i.message, i.source) for i in issues
    ]
    return _compute_uncertainty(converted)


def snapshot_from_state(state: Dict[str, Any], stage: str) -> StageSnapshot:
    issues = run_staged_checks(state, stage)
    tables, _ = parse_schema_catalog(state.get("schema_summary") or "")
    contracts = _collect_contract_text(state)
    matrix = compute_disagreement_matrix(contracts, tables)
    return StageSnapshot(
        stage=stage,
        issue_count=len(issues),
        critical_count=sum(1 for i in issues if i.severity == "critical"),
        uncertainty=_stage_uncertainty(issues),
        disagreement=aggregate_disagreement(matrix),
    )


def build_full_issue_list(state: Dict[str, Any]) -> List[ReliabilityIssue]:
    result = run_deterministic_contract_checks(state)
    return [
        ReliabilityIssue(
            severity=i.severity,
            failure_type=i.failure_type,
            source=i.source,
            message=i.message,
            stage=i.source,
        )
        for i in result.issues
    ]


def build_reliability_report(
    state: Dict[str, Any],
    *,
    cav_passed: bool = True,
    cav_llm_verdict: Optional[str] = None,
    self_verification: Optional[Dict[str, bool]] = None,
    mitigations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    issues = build_full_issue_list(state)
    contracts = _collect_contract_text(state)
    tables, _ = parse_schema_catalog(state.get("schema_summary") or "")
    matrix = compute_disagreement_matrix(contracts, tables)
    dis_score = aggregate_disagreement(matrix)

    converted = [
        ContractIssue(i.severity, i.failure_type, i.message, i.source) for i in issues
    ]
    uncertainty = _compute_uncertainty(converted)

    snapshots = []
    for st in ("post_cip", "post_at", "post_nj"):
        if st == "post_at" and not contracts.get("at"):
            continue
        if st == "post_nj" and not contracts.get("nj"):
            continue
        snapshots.append(snapshot_from_state(state, st))

    propagation_prevented = state.get("contract_valid") is False and not state.get("sql")
    repair_count = state.get("contract_repair_count", 0) or 0
    repair_attempted = repair_count > 0
    repair_succeeded = repair_attempted and state.get("contract_valid") is True

    report = build_report_from_issues(
        issues,
        disagreement_matrix=matrix,
        disagreement_score=dis_score,
        uncertainty_score=max(uncertainty, state.get("contract_uncertainty") or 0.0),
        cav_passed=cav_passed,
        cav_llm_verdict=cav_llm_verdict,
        self_verification=self_verification,
        mitigations=mitigations or _default_mitigations(state),
        stage_snapshots=snapshots,
        propagation_prevented=propagation_prevented,
        repair_attempted=repair_attempted,
        repair_succeeded=repair_succeeded,
        failure_stage=_failure_stage(state, issues, cav_passed),
    )
    return report.to_dict()


def _default_mitigations(state: Dict[str, Any]) -> List[str]:
    m: List[str] = ["retrieval_grounding"]
    if state.get("needs_clarification"):
        m.append("clarification_gate")
    if state.get("contract_repair_count", 0):
        m.append("contract_repair")
    if state.get("contract_valid") is False:
        m.append("cross_agent_validation")
    elif state.get("contract_valid") is True:
        m.extend(["cross_agent_validation", "self_verification"])
    if state.get("refinement_count", 0):
        m.append("execution_guided_repair")
    return list(dict.fromkeys(m))


def _failure_stage(
    state: Dict[str, Any],
    issues: List[ReliabilityIssue],
    cav_passed: bool,
) -> Optional[str]:
    if state.get("contract_valid") is False and not cav_passed:
        return AgentStage.CAV.value
    if not issues:
        return None
    critical = [i for i in issues if i.severity == "critical"]
    pool = critical or issues
    return pool[0].stage or pool[0].source
