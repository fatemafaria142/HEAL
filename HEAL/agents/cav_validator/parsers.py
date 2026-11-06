from __future__ import annotations

import json
import re
from typing import Optional


def escape_braces(text: str) -> str:
    return (text or "").replace("{", "{{").replace("}", "}}")


def parse_structured_verdict(content: str) -> tuple[bool, str, Optional[str]]:
    text = (content or "").strip()
    failure_type = None

    json_block = text
    if "```json" in text:
        json_block = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        json_block = text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(json_block)
        consistent = str(data.get("verdict", "")).upper() == "CONSISTENT"
        failure_type = data.get("primary_failure_type")
        return consistent, text, failure_type
    except json.JSONDecodeError:
        pass

    upper = text.upper()
    first = upper.split("\n", 1)[0].strip()
    m = re.search(r"failure_type:\s*(\w[\w-]*)", text, re.I)
    if m:
        failure_type = m.group(1).lower()
    if first.startswith("CONSISTENT"):
        return True, text, failure_type
    if first.startswith("INCONSISTENT") or "INCONSISTENT" in first[:24]:
        return False, text, failure_type
    if "CONSISTENT" in first and "INCONSISTENT" not in first:
        return True, text, failure_type
    return False, text or "CAV returned an unparseable verdict.", failure_type
