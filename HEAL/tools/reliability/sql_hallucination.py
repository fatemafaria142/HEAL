from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlparse

from HEAL.tools.reliability.taxonomy import AgentStage, FailureType, ReliabilityIssue, Severity


_IDENT = r"[a-zA-Z_][a-zA-Z0-9_]*"

_TABLE_SOURCE = re.compile(
    rf"\b(?:FROM|JOIN)\s+(?:ONLY\s+)?({_IDENT})(?:\s+(?:AS\s+)?({_IDENT}))?",
    re.I,
)
_DERIVED_SOURCE = re.compile(rf"\b(?:FROM|JOIN)\s*\(\s*SELECT\b.*?\)\s*(?:AS\s+)?({_IDENT})", re.I | re.S)
_CTE_NAME = re.compile(rf"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)({_IDENT})\s+AS\s*\(", re.I)
_QUALIFIED = re.compile(rf"\b({_IDENT})\.({_IDENT})\b")

_NOT_A_TABLE = frozenset(
    {
        "select", "where", "group", "order", "having", "limit", "offset", "on",
        "and", "or", "not", "in", "as", "by", "lateral", "unnest", "generate_series",
        "values", "using", "cross", "natural", "inner", "left", "right", "full", "outer",
    }
)

_PSEUDO_PREFIX = frozenset({"extract", "interval", "current_date", "current_timestamp", "now"})


@dataclass
class SQLGroundingResult:
    unknown_tables: List[str] = field(default_factory=list)
    unknown_columns: List[Tuple[str, str]] = field(default_factory=list)
    checked_tables: Set[str] = field(default_factory=set)
    checked_refs: int = 0
    skipped_prefixes: Set[str] = field(default_factory=set)

    @property
    def hallucinated(self) -> bool:
        return bool(self.unknown_tables or self.unknown_columns)

    @property
    def count(self) -> int:
        return len(self.unknown_tables) + len(self.unknown_columns)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hallucinated": self.hallucinated,
            "unknown_tables": sorted(self.unknown_tables),
            "unknown_columns": [f"{t}.{c}" for t, c in sorted(self.unknown_columns)],
            "hallucinated_identifier_count": self.count,
            "tables_referenced": sorted(self.checked_tables),
            "qualified_refs_checked": self.checked_refs,
        }

    def summary(self) -> str:
        parts = []
        if self.unknown_tables:
            parts.append("unknown table(s): " + ", ".join(sorted(self.unknown_tables)))
        if self.unknown_columns:
            parts.append(
                "unknown column(s): "
                + ", ".join(f"{t}.{c}" for t, c in sorted(self.unknown_columns))
            )
        return "; ".join(parts)


_FROM_FUNCS = re.compile(r"\b(?:EXTRACT|SUBSTRING|TRIM|POSITION|OVERLAY)\s*\(", re.I)


def _strip_noise(sql: str) -> str:
    cleaned = sqlparse.format(sql or "", strip_comments=True, keyword_case="upper")
    cleaned = re.sub(r"'(?:[^']|'')*'", "''", cleaned)
    cleaned = re.sub(r'"(?:[^"]|"")*"', '""', cleaned)
    return cleaned


def _blank_from_functions(sql: str) -> str:
    out = sql
    while True:
        m = _FROM_FUNCS.search(out)
        if not m:
            return out
        open_paren = m.end() - 1
        depth = 0
        end = -1
        for i in range(open_paren, len(out)):
            if out[i] == "(":
                depth += 1
            elif out[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            return out
        out = out[: m.start()] + " " * (end - m.start() + 1) + out[end + 1 :]


def _collect_sources(sql: str) -> Tuple[Dict[str, str], Set[str], Set[str]]:
    alias_map: Dict[str, str] = {}
    real_tables: Set[str] = set()
    opaque: Set[str] = {m.group(1).lower() for m in _CTE_NAME.finditer(sql)}
    opaque |= {m.group(1).lower() for m in _DERIVED_SOURCE.finditer(sql)}

    for m in _TABLE_SOURCE.finditer(sql):
        table = m.group(1).lower()
        alias = (m.group(2) or "").lower()
        if table in _NOT_A_TABLE:
            continue
        if table in opaque:
            if alias and alias not in _NOT_A_TABLE:
                opaque.add(alias)
            continue
        real_tables.add(table)
        alias_map[table] = table
        if alias and alias not in _NOT_A_TABLE:
            alias_map[alias] = table

    return alias_map, real_tables, opaque


def ground_sql_in_schema(
    sql: str,
    tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
) -> SQLGroundingResult:
    result = SQLGroundingResult()
    if not sql or not sql.strip() or not tables:
        return result

    cleaned = _strip_noise(sql)
    alias_map, real_tables, opaque = _collect_sources(_blank_from_functions(cleaned))

    for table in sorted(real_tables):
        result.checked_tables.add(table)
        if table not in tables:
            result.unknown_tables.append(table)

    seen: Set[Tuple[str, str]] = set()
    for m in _QUALIFIED.finditer(cleaned):
        prefix, column = m.group(1).lower(), m.group(2).lower()
        if prefix in _PSEUDO_PREFIX or prefix in opaque or prefix in _NOT_A_TABLE:
            result.skipped_prefixes.add(prefix)
            continue

        table = alias_map.get(prefix)
        if table is None:
            result.skipped_prefixes.add(prefix)
            continue
        if table not in tables:
            continue

        known = columns_by_table.get(table)
        if not known:
            continue
        result.checked_refs += 1
        if column not in known and (table, column) not in seen:
            seen.add((table, column))
            result.unknown_columns.append((table, column))

    return result


def sql_hallucination_issues(
    sql: str,
    tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
    *,
    stage: str = AgentStage.S3.value,
) -> List[ReliabilityIssue]:
    result = ground_sql_in_schema(sql, tables, columns_by_table)
    issues: List[ReliabilityIssue] = []

    for table in result.unknown_tables:
        issues.append(
            ReliabilityIssue(
                severity=Severity.CRITICAL.value,
                failure_type=FailureType.RETRIEVAL.value,
                source=stage,
                stage=stage,
                message=(
                    f"Generated SQL references table `{table}`, which does not exist "
                    "in the live PostgreSQL schema."
                ),
            )
        )
    for table, column in result.unknown_columns:
        issues.append(
            ReliabilityIssue(
                severity=Severity.CRITICAL.value,
                failure_type=FailureType.RETRIEVAL.value,
                source=stage,
                stage=stage,
                message=(
                    f"Generated SQL references column `{table}.{column}`, which does not "
                    f"exist on table `{table}`."
                ),
            )
        )
    return issues


def ground_sql_from_state(state: Dict[str, Any], sql: Optional[str] = None) -> SQLGroundingResult:
    from HEAL.tools.guards.contract_guard import parse_schema_catalog

    tables, columns_by_table = parse_schema_catalog(state.get("schema_summary") or "")
    return ground_sql_in_schema(sql or state.get("sql") or "", tables, columns_by_table)
