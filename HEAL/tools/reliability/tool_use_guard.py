from __future__ import annotations

import re
from typing import List

from HEAL.tools.reliability.taxonomy import ReliabilityIssue, Severity, FailureType, AgentStage

_DUAL_JOIN_SAME = re.compile(
    r"join\s+(\w+)\s+\w+\s+join\s+\1\b",
    re.I,
)
_SELF_JOIN_CARTESIAN = re.compile(
    r"(\w+)\s+\w+\s+join\s+\1\s+\w+\s+on\s+\w+\.patient_id\s*=\s*\w+\.patient_id",
    re.I,
)
_EXISTS_RECOMMENDED = re.compile(r"\bEXISTS\b", re.I)
_BOTH_CONSTRAINT = re.compile(r"\bboth\b.*\b(and|&)\b", re.I)


def check_tool_use_patterns(join_nest_plan: str) -> List[ReliabilityIssue]:
    issues: List[ReliabilityIssue] = []
    text = join_nest_plan or ""
    if not text.strip():
        return issues

    if _DUAL_JOIN_SAME.search(text) and not _EXISTS_RECOMMENDED.search(text):
        issues.append(
            ReliabilityIssue(
                severity=Severity.CRITICAL.value,
                failure_type=FailureType.TOOL_USE.value,
                source=AgentStage.NJ.value,
                stage=AgentStage.NJ.value,
                message=(
                    "HEAL-NJ plans duplicate JOIN on the same table without EXISTS — "
                    "likely cartesian row explosion (tool-use failure)."
                ),
            )
        )

    if _BOTH_CONSTRAINT.search(text) and _SELF_JOIN_CARTESIAN.search(text):
        issues.append(
            ReliabilityIssue(
                severity=Severity.WARNING.value,
                failure_type=FailureType.TOOL_USE.value,
                source=AgentStage.NJ.value,
                stage=AgentStage.NJ.value,
                message=(
                    "Dual-constraint intent with self-join pattern — prefer EXISTS/HAVING "
                    "over pairing filtered subsets."
                ),
            )
        )
    return issues
