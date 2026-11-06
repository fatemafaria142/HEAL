from __future__ import annotations

import json
from typing import Dict


def escape_braces(text: str) -> str:
    return (text or "").replace("{", "{{").replace("}", "}}")


def parse_verification_json(content: str) -> Dict[str, bool]:
    text = content.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        data = json.loads(text)
        return {
            "cip": bool(data.get("cip_verified", True)),
            "at": bool(data.get("at_verified", True)),
            "nj": bool(data.get("nj_verified", True)),
        }
    except json.JSONDecodeError:
        lowered = text.lower()
        return {
            "cip": "cip_verified" not in lowered or "false" not in lowered.split("cip")[0],
            "at": "at_verified" not in lowered or '"at_verified": false' not in lowered,
            "nj": "nj_verified" not in lowered or '"nj_verified": false' not in lowered,
        }
