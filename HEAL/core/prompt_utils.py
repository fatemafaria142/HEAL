from __future__ import annotations

from typing import Any, Dict


def render_prompt_template(template: str, variables: Dict[str, Any]) -> str:
    out = template
    for key, value in variables.items():
        out = out.replace("{" + key + "}", str(value if value is not None else ""))
    return out
