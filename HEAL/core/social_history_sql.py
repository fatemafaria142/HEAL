from __future__ import annotations

import re
from typing import Tuple

_ONGOING_TOBACCO = re.compile(
    r"\b("
    r"regular\s+tobacco|regular\s+smok|tobacco\s+users?|active\s+smok|current\s+tobacco|"
    r"current\s+smok|people\s+who\s+smoke|\bsmokers?\b|\bsmoking\b|cigarette|nicotine|"
    r"\btobacco\b"
    r")\b",
    re.I,
)

_FORMER_TOBACCO = re.compile(
    r"\b(former\s+smok|ex[- ]?smok|quit\s+smoking|stopped\s+smoking|used\s+to\s+smoke)\b",
    re.I,
)


def tobacco_intent(user_query: str | None) -> str | None:
    if not user_query or not str(user_query).strip():
        return None
    if _FORMER_TOBACCO.search(user_query):
        return "former"
    if _ONGOING_TOBACCO.search(user_query):
        return "ongoing"
    return None


def normalize_tobacco_use_sql(sql: str, user_query: str | None) -> Tuple[str, bool]:
    if tobacco_intent(user_query) != "ongoing":
        return sql, False
    if not sql or "tobacco_use" not in sql.lower():
        return sql, False

    original = sql
    s = sql

    s = re.sub(r"(?i)%regular%", "%Current%", s)

    s = re.sub(
        r"((?:[\w]+\.)?tobacco_use\s*=\s*')regular'",
        r"\1Current'",
        s,
        flags=re.I,
    )
    s = re.sub(
        r'((?:[\w]+\.)?tobacco_use\s*=\s*")regular"',
        r'\1Current"',
        s,
        flags=re.I,
    )

    return s, s != original
