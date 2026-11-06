from __future__ import annotations

import re
from typing import Dict, List, Set

from HEAL.tools.reliability.taxonomy import ReliabilityIssue, Severity, FailureType, AgentStage

_VOCAB_LINE = re.compile(r"^####\s+(.+?)\s+\(`([^`]+)`\)", re.M)
_RANKED_TERM = re.compile(r"`([^`]+)`\s*×\d+")


def parse_vocab_terms(vocab_snippet: str) -> Dict[str, Set[str]]:
    catalog: Dict[str, Set[str]] = {}
    if not vocab_snippet:
        return catalog
    current_key: str | None = None
    for line in vocab_snippet.splitlines():
        m_hdr = _VOCAB_LINE.match(line.strip())
        if m_hdr:
            current_key = m_hdr.group(2).lower()
            catalog.setdefault(current_key, set())
            continue
        if current_key and "`" in line:
            for term in _RANKED_TERM.findall(line):
                catalog[current_key].add(term.lower())
    return catalog


_GLYCEMIC_ONLY = re.compile(r"\b(hba1c|a1c|glycemic|glucose)\b", re.I)
_HEMATOLOGY = re.compile(r"\b(hemoglobin|hgb|hct|ferritin|anemia|anaemia)\b", re.I)
_ANEMIA_INTENT = re.compile(r"\b(anemia|anaemia|anemic|iron\s+deficiency)\b", re.I)


def check_vocab_domain_alignment(
    intent_text: str,
    at_resolution: str,
    catalog: Dict[str, Set[str]],
) -> List[ReliabilityIssue]:
    issues: List[ReliabilityIssue] = []
    if not _ANEMIA_INTENT.search(intent_text):
        return issues

    at_lower = (at_resolution or "").lower()
    if _HEMATOLOGY.search(at_lower):
        return issues

    if _GLYCEMIC_ONLY.search(at_lower):
        lab_terms = catalog.get("lab_results.test_name", set())
        has_heme_in_db = any(_HEMATOLOGY.search(t) for t in lab_terms)
        if has_heme_in_db:
            issues.append(
                ReliabilityIssue(
                    severity=Severity.CRITICAL.value,
                    failure_type=FailureType.REASONING.value,
                    source=AgentStage.AT.value,
                    stage=AgentStage.AT.value,
                    message=(
                        "Anemia intent resolved to glycemic labs only, but live DB vocabulary "
                        "contains hematology tests — retrieval-grounding failure."
                    ),
                )
            )
    return issues
