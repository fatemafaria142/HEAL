from __future__ import annotations

import re
from typing import Tuple

_FORBIDDEN = re.compile(
    r"\b("
    r"delete|update|insert|drop|alter|create|truncate|grant|revoke|merge|replace\s+into"
    r")\b",
    re.I | re.DOTALL,
)


def validate_read_only_select(sql: str | None) -> Tuple[bool, str]:
    if sql is None:
        return False, "SQL is missing."
    raw = sql.strip()
    if not raw:
        return False, "SQL is empty."

    lines = []
    for line in raw.split("\n"):
        ls = line.strip()
        if ls.startswith("--"):
            continue
        lines.append(line)
    s = "\n".join(lines).strip()
    if not s:
        return False, "SQL is empty after removing comments."

    core = s.rstrip().rstrip(";")
    if ";" in core:
        return False, "Multiple SQL statements are not allowed."

    head = s.lstrip().upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        return False, "Only SELECT or WITH (CTE) read queries are allowed."

    if _FORBIDDEN.search(s):
        return False, "Disallowed keyword detected (non-read-only SQL)."

    return True, ""
