from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from HEAL.tools.guards.clinical_domain_guard import anemia_hba1c_domain_clash, combined_clinical_intent

_TABLE_HEADER = re.compile(r"^####\s+Table\s+`([a-zA-Z_][a-zA-Z0-9_]*)`", re.M)
_COLUMN_LINE = re.compile(r"^\s*-\s+`([a-zA-Z_][a-zA-Z0-9_]*)`\s+—", re.M)
_QUALIFIED_REF = re.compile(r"\b([a-z][a-z0-9_]{2,})\.([a-z][a-z0-9_]+)\b", re.I)
_BACKTICK_TABLE = re.compile(r"`([a-z][a-z0-9_]*)`", re.I)
_POPULATION_GRAIN = re.compile(
    r"\b(population|monthly|per\s+month|by\s+month|DATE_TRUNC|time\s+bucket|aggregate\s+trend)\b",
    re.I,
)
_PATIENT_GRAIN = re.compile(
    r"\b(one\s+row\s+per\s+patient|per\s+patient|distinct\s+patients?|patient[- ]level|"
    r"each\s+patient|list\s+patients?)\b",
    re.I,
)
_VISIT_DATE_ANCHOR = re.compile(r"\b(visit_date|encounter\s+date|visit\s+date)\b", re.I)
_MEASUREMENT_DATE_ANCHOR = re.compile(
    r"\b(recorded_date|test_date|measurement\s+date|lab\s+date)\b", re.I,
)

_PROSE_FALSE_POSITIVES = frozenset(
    {
        "select",
        "where",
        "from",
        "join",
        "group",
        "order",
        "limit",
        "with",
        "exists",
        "having",
        "null",
        "true",
        "false",
        "current_date",
        "date_trunc",
        "row_number",
        "distinct",
        "count",
        "avg",
        "min",
        "max",
        "partition",
        "over",
        "asc",
        "desc",
        "between",
        "ilike",
        "and",
        "or",
        "not",
        "in",
        "as",
        "on",
        "by",
        "month",
        "year",
        "day",
        "week",
        "rn",
        "pk",
        "fk",
    }
)


@dataclass
class ContractIssue:
    severity: str
    failure_type: str
    message: str
    source: str


@dataclass
class ContractValidationResult:
    issues: List[ContractIssue] = field(default_factory=list)
    uncertainty_score: float = 0.0

    @property
    def critical_issues(self) -> List[ContractIssue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def has_critical(self) -> bool:
        return bool(self.critical_issues)

    def summary(self) -> str:
        if not self.issues:
            return "All planning contracts passed schema-grounded checks."
        lines = []
        for issue in self.issues:
            lines.append(f"[{issue.severity}/{issue.failure_type}/{issue.source}] {issue.message}")
        return "\n".join(lines)


def parse_schema_catalog(schema_summary: str) -> Tuple[Set[str], Dict[str, Set[str]]]:
    tables: Set[str] = set()
    columns_by_table: Dict[str, Set[str]] = {}
    if not schema_summary:
        return tables, columns_by_table

    current_table: Optional[str] = None
    for line in schema_summary.splitlines():
        m_table = _TABLE_HEADER.match(line)
        if m_table:
            current_table = m_table.group(1).lower()
            tables.add(current_table)
            columns_by_table.setdefault(current_table, set())
            continue
        if current_table:
            m_col = _COLUMN_LINE.match(line)
            if m_col:
                columns_by_table[current_table].add(m_col.group(1).lower())
    return tables, columns_by_table


def _collect_contract_text(state: Dict[str, Any]) -> Dict[str, str]:
    return {
        "cip": (state.get("clinical_plan") or "").strip(),
        "at": (state.get("anjt_resolution") or "").strip(),
        "nj": (state.get("join_nest_plan") or "").strip(),
    }


_PROSE_STOPWORDS = _PROSE_FALSE_POSITIVES | frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "path",
        "plan",
        "grain",
        "nested",
        "logic",
        "cohort",
        "window",
        "last",
        "days",
        "use",
        "using",
        "via",
        "for",
        "with",
        "one",
        "two",
        "same",
        "each",
        "all",
        "any",
        "both",
        "step",
        "filter",
        "filters",
        "output",
        "input",
        "list",
        "show",
        "high",
        "blood",
        "pressure",
        "g",
        "i",
        "e",
        "id",
    }
)


def _all_columns(columns_by_table: Dict[str, Set[str]]) -> Set[str]:
    cols: Set[str] = set()
    for colset in columns_by_table.values():
        cols.update(colset)
    return cols


def _extract_schema_refs(
    text: str,
    tables: Set[str],
    all_columns: Set[str],
) -> Set[Tuple[str, Optional[str]]]:
    refs: Set[Tuple[str, Optional[str]]] = set()
    if not text:
        return refs

    scrubbed = re.sub(r"\be\.g\.\b", " ", text, flags=re.I)

    for table, col in _QUALIFIED_REF.findall(scrubbed):
        t, c = table.lower(), col.lower()
        if t in _PROSE_STOPWORDS or t in all_columns:
            continue
        if c in _PROSE_STOPWORDS:
            continue
        refs.add((t, c))

    for match in re.finditer(
        r"\b(?:from|join)\s+([a-z][a-z0-9_]{3,})\b", scrubbed, re.I
    ):
        t = match.group(1).lower()
        if t in _PROSE_STOPWORDS or t in all_columns or t in tables:
            continue
        if t.endswith("s") or t.endswith("_results") or t.endswith("_history"):
            refs.add((t, None))

    for match in _BACKTICK_TABLE.finditer(scrubbed):
        token = match.group(1).lower()
        if token in tables or token in all_columns or token in _PROSE_STOPWORDS:
            continue
        if token.endswith("s") and len(token) >= 5:
            refs.add((token, None))
        elif any(token.endswith(sfx) for sfx in ("_records", "_history", "_codes", "_data")):
            refs.add((token, None))

    return refs


def _check_schema_grounding(
    contracts: Dict[str, str],
    tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
) -> List[ContractIssue]:
    issues: List[ContractIssue] = []
    if not tables:
        return issues

    all_columns = _all_columns(columns_by_table)

    for source, text in contracts.items():
        for table, col in _extract_schema_refs(text, tables, all_columns):
            if table in all_columns and table not in tables:
                continue
            if table not in tables:
                issues.append(
                    ContractIssue(
                        severity="critical",
                        failure_type="retrieval",
                        source=source,
                        message=(
                            f"References unknown table `{table}` — not in live schema. "
                            "Downstream SQL would hallucinate schema objects."
                        ),
                    )
                )
                continue
            if col and col not in columns_by_table.get(table, set()):
                issues.append(
                    ContractIssue(
                        severity="critical",
                        failure_type="retrieval",
                        source=source,
                        message=(
                            f"References unknown column `{table}.{col}` — not in live schema."
                        ),
                    )
                )
    return issues


def _check_domain_alignment(state: Dict[str, Any]) -> List[ContractIssue]:
    intent = combined_clinical_intent(state)
    clash = anemia_hba1c_domain_clash(intent, intent)
    if not clash:
        return []
    return [
        ContractIssue(
            severity="critical",
            failure_type="reasoning",
            source="cross",
            message=clash,
        )
    ]


def _check_grain_contradiction(contracts: Dict[str, str]) -> List[ContractIssue]:
    cip = contracts.get("cip") or ""
    nj = contracts.get("nj") or ""
    if not cip or not nj:
        return []

    cip_patient = bool(_PATIENT_GRAIN.search(cip))
    nj_population = bool(_POPULATION_GRAIN.search(nj))
    nj_patient = bool(_PATIENT_GRAIN.search(nj))

    if cip_patient and nj_population and not nj_patient:
        return [
            ContractIssue(
                severity="critical",
                failure_type="reasoning",
                source="cross",
                message=(
                    "CIP expects patient-level grain but HEAL-NJ plans a population/monthly aggregate. "
                    "This mismatch will propagate wrong SQL shape."
                ),
            )
        ]
    return []


def _check_temporal_anchor_contradiction(contracts: Dict[str, str]) -> List[ContractIssue]:
    at = contracts.get("at") or ""
    nj = contracts.get("nj") or ""
    if not at or not nj:
        return []

    at_visit = bool(_VISIT_DATE_ANCHOR.search(at))
    at_measure = bool(_MEASUREMENT_DATE_ANCHOR.search(at))
    nj_visit = bool(_VISIT_DATE_ANCHOR.search(nj))
    nj_measure = bool(_MEASUREMENT_DATE_ANCHOR.search(nj))

    if at_measure and nj_visit and not nj_measure:
        return [
            ContractIssue(
                severity="warning",
                failure_type="reasoning",
                source="cross",
                message=(
                    "HEAL-AT anchors time on measurement/lab dates but HEAL-NJ emphasizes visit_date. "
                    "Agents disagree on temporal anchor — high uncertainty."
                ),
            )
        ]
    if at_visit and nj_measure and not nj_visit:
        return [
            ContractIssue(
                severity="warning",
                failure_type="reasoning",
                source="cross",
                message=(
                    "HEAL-AT anchors on visit/encounter dates but HEAL-NJ emphasizes measurement dates. "
                    "Agents disagree on temporal anchor — high uncertainty."
                ),
            )
        ]
    return []


def _check_empty_contracts(state: Dict[str, Any]) -> List[ContractIssue]:
    issues: List[ContractIssue] = []
    if not (state.get("clinical_plan") or "").strip():
        issues.append(
            ContractIssue(
                severity="critical",
                failure_type="reasoning",
                source="cip",
                message="Missing clinical plan from CIP — cannot safely generate SQL.",
            )
        )
    if not (state.get("anjt_resolution") or "").strip():
        issues.append(
            ContractIssue(
                severity="warning",
                failure_type="reasoning",
                source="at",
                message="Missing HEAL-AT resolution — ambiguity/temporal logic not locked.",
            )
        )
    if not (state.get("join_nest_plan") or "").strip():
        issues.append(
            ContractIssue(
                severity="warning",
                failure_type="reasoning",
                source="nj",
                message="Missing HEAL-NJ join/nest plan — relational shape not specified.",
            )
        )
    return issues


def _compute_uncertainty(issues: List[ContractIssue]) -> float:
    if not issues:
        return 0.0
    score = 0.0
    for issue in issues:
        if issue.severity == "critical":
            score += 0.45
        else:
            score += 0.2
    return min(1.0, score)


def run_deterministic_contract_checks(state: Dict[str, Any]) -> ContractValidationResult:
    contracts = _collect_contract_text(state)
    tables, columns_by_table = parse_schema_catalog(state.get("schema_summary") or "")

    issues: List[ContractIssue] = []
    issues.extend(_check_empty_contracts(state))
    issues.extend(_check_schema_grounding(contracts, tables, columns_by_table))
    issues.extend(_check_domain_alignment(state))
    issues.extend(_check_grain_contradiction(contracts))
    issues.extend(_check_temporal_anchor_contradiction(contracts))
    issues.extend(_extended_reliability_checks(state, contracts, tables))

    return ContractValidationResult(
        issues=issues,
        uncertainty_score=_compute_uncertainty(issues),
    )


def _extended_reliability_checks(
    state: Dict[str, Any],
    contracts: Dict[str, str],
    tables: Set[str],
) -> List[ContractIssue]:
    from HEAL.tools.reliability.disagreement import compute_disagreement_matrix, disagreement_issues
    from HEAL.tools.reliability.memory_guard import check_memory_retention
    from HEAL.tools.reliability.tool_use_guard import check_tool_use_patterns
    from HEAL.tools.reliability.vocab_guard import check_vocab_domain_alignment, parse_vocab_terms

    out: List[ContractIssue] = []
    for ri in check_memory_retention(state):
        out.append(ContractIssue(ri.severity, ri.failure_type, ri.message, ri.source))
    for ri in check_tool_use_patterns(contracts.get("nj", "")):
        out.append(ContractIssue(ri.severity, ri.failure_type, ri.message, ri.source))
    catalog = parse_vocab_terms(state.get("schema_vocab_snippet") or "")
    for ri in check_vocab_domain_alignment(
        combined_clinical_intent(state), contracts.get("at", ""), catalog
    ):
        out.append(ContractIssue(ri.severity, ri.failure_type, ri.message, ri.source))
    matrix = compute_disagreement_matrix(contracts, tables)
    for ri in disagreement_issues(matrix):
        out.append(ContractIssue(ri.severity, ri.failure_type, ri.message, ri.source))
    return out
