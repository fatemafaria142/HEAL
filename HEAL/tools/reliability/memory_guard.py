from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from HEAL.tools.reliability.taxonomy import ReliabilityIssue, Severity, FailureType, AgentStage

_COREFERENCE = re.compile(
    r"\b(those|their|them|same\s+(group|cohort|patients?)|only\s+those|"
    r"from\s+before|previous|earlier|above|still|also\s+restrict)\b",
    re.I,
)
_HISTORY_FILTER = re.compile(
    r"(ILIKE\s+'[^']+'|=\s*'[^']+'|>\s*\d+|<\s*\d+|BETWEEN|diagnosis_name|test_name|"
    r"department|gender|city|age|hypertension|diabetes|hba1c|asthma)",
    re.I,
)
_PLAN_MENTIONS = re.compile(
    r"\b(retain|carry|previous|prior|turn\s+\d|history|same\s+cohort)\b",
    re.I,
)


def _extract_history_signals(history_summary: str) -> Set[str]:
    signals: Set[str] = set()
    if not history_summary or history_summary.startswith("No previous"):
        return signals
    for m in _HISTORY_FILTER.finditer(history_summary):
        signals.add(m.group(0).lower()[:40])
    return signals


def check_memory_retention(state: Dict[str, Any]) -> List[ReliabilityIssue]:
    query = state.get("query") or ""
    history = state.get("history_summary") or ""
    if not _COREFERENCE.search(query):
        return []

    prior_signals = _extract_history_signals(history)
    if not prior_signals:
        return []

    combined = " ".join(
        filter(
            None,
            [
                state.get("clinical_plan"),
                state.get("anjt_resolution"),
                state.get("join_nest_plan"),
            ],
        )
    )
    if _PLAN_MENTIONS.search(combined):
        return []

    overlap = sum(1 for s in prior_signals if s in combined.lower())
    if overlap >= max(1, len(prior_signals) // 4):
        return []

    return [
        ReliabilityIssue(
            severity=Severity.WARNING.value,
            failure_type=FailureType.MEMORY.value,
            source=AgentStage.CROSS.value,
            stage=AgentStage.CIP.value,
            message=(
                "Follow-up query corefers to prior turn but planning contracts do not "
                "explicitly retain prior cohort constraints — possible memory failure."
            ),
        )
    ]
