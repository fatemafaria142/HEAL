from __future__ import annotations

import re
from typing import Any, Dict, Optional

_ANEMIA_USER = re.compile(
    r"\b(anemia|anaemia|anemic|hypochromic|microcytic|macrocytic|sideropenic)\b|"
    r"iron\s+deficiency(?:\s+anemia)?|aplastic\s+anemia|\bIDA\b|thalassemia\b|"
    r"low\s+(hemoglobin|hematocrit|\bhgb\b|\bhct\b|rbc\b)|"
    r"\b(hgb|hb)\s+(low|decreased)|"
    r"(?:need|needed)\s+(iron|transfusion)|"
    r"\bhemoglobin\b.*\b(low|decrease)",
    re.I,
)


def combined_clinical_intent(state: Dict[str, Any]) -> str:
    parts = [
        state.get("query") or "",
        state.get("clinical_plan") or "",
        state.get("anjt_resolution") or "",
        state.get("join_nest_plan") or "",
    ]
    return "\n".join(p.strip() for p in parts if p and str(p).strip())

_ANEMIA_SQL_MARKERS = re.compile(
    r"(anemia|anaemia|iron\s+deficiency|hypochrom|aplastic|hemoglobin|hematocrit|\bhgb\b|\bhct\b|ferritin|cbc\b|rbc\b)",
    re.I,
)

_GLYCEMIC_LAB_FILTER = re.compile(
    r"(hba1c|hb\s*a1c|\ba1c\b|glycated\s+hemoglobin|glycemic\b|"
    r"%glycat|%hba1c|%a1c|random\s+glucose|fasting\s+glucose)",
    re.I,
)


def anemia_hba1c_domain_clash(user_query: str, sql: str) -> Optional[str]:
    if not user_query or not sql:
        return None
    if not _ANEMIA_USER.search(user_query):
        return None
    if not _GLYCEMIC_LAB_FILTER.search(sql):
        return None
    if _ANEMIA_SQL_MARKERS.search(sql):
        return None
    return (
        "Clinical domain mismatch: the question concerns **anemia / iron deficiency**, "
        "but the SQL filters **HbA1c or other glycemic labs**, which do not define anemia. "
        "Rewrite using **`diagnoses.diagnosis_name`** with `ILIKE` on anemia-related terms "
        "(e.g. anemia, iron deficiency, hemoglobin) **and/or** "
        "`lab_results` where `test_name` matches **hematology** (hemoglobin, HCT, ferritin, CBC), "
        "not HbA1c."
    )
