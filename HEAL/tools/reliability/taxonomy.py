from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class FailureType(str, Enum):
    RETRIEVAL = "retrieval"
    REASONING = "reasoning"
    MEMORY = "memory"
    TOOL_USE = "tool-use"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"


class AgentStage(str, Enum):
    CIP = "cip"
    AT = "at"
    NJ = "nj"
    CROSS = "cross"
    CAV = "cav"
    S3 = "s3"
    DFA = "dfa"
    EGR = "egr"
    EBS = "ebs"


@dataclass
class ReliabilityIssue:
    severity: str
    failure_type: str
    source: str
    message: str
    stage: str = "cross"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def primary_failure_type(issues: List[ReliabilityIssue]) -> Optional[str]:
    if not issues:
        return None
    ranked = sorted(
        issues,
        key=lambda i: (0 if i.severity == Severity.CRITICAL.value else 1),
    )
    return ranked[0].failure_type
