import re

CLINICAL_HINT = re.compile(
    r"\b(labs?\b|lab\s+results?\b|hba1c|glycemic|glucose|a1c|creatinine|ldl|hdl|"
    r"cholesterol|lipid|triglycer|inr|tsh|crp|vitals?\b|blood\s+pressure|\bbp\b|"
    r"systolic|diastolic|hypertens|diagnos|diabetes|prescription|medication|drug|"
    r"dose|imaging|x-ray|xray|ct\b|mri|ultrasound|oxygen|spo2|fever|temperature|"
    r"bmi|note|hemoglobin|platelet|wbc|renal|liver\s+function|tobacco|smok|"
    r"cigarette|nicotine|alcohol|weight|weigh|kg\b|kilogram|gained|gain|lost|loss|"
    r"change\s+in\s+weight)\b",
    re.I,
)

EVIDENCE_IN_SELECT = re.compile(
    r"\b(result_value|test_name|test_date|bp_systolic|bp_diastolic|diagnosis_name|"
    r"medication|dosage|diagnosis_date|recorded_date|visit_date|flag|unit|icd10|"
    r"tobacco_use|alcohol_use|weight|height|\bbmi\b|heart_rate|temperature|"
    r"vital_id|visit_id|indication|procedure_name|procedure_date|note_text|findings|"
    r"imaging_type|imaging_date|body_site|hospital|visit_type|department|"
    r"prescribing_doctor|procedure_code|icd10)\b",
    re.I,
)

CLINICAL_TABLE = re.compile(
    r"\b(lab_results|vitals|diagnoses|prescriptions|procedures|clinical_notes|"
    r"imaging_results|social_history)\b",
    re.I,
)


def is_population_period_aggregate(sql: str) -> bool:
    low = sql.lower()
    if "date_trunc" not in low and "extract(" not in low:
        return False
    if "group by" not in low:
        return False
    if not re.search(r"\b(avg|sum|count|min|max)\s*\(", low):
        return False
    if re.search(r"\bgroup\s+by\s+[^;]+?\bpatient_id\b", low, re.S | re.I):
        return False
    return True


def projection_clause(sql: str) -> str:
    m = re.search(
        r"(?is)\bselect\s+(distinct\s+on\s*\([^)]+\)\s*)?(distinct\s+)?(.+?)\s+from\b",
        sql,
    )
    return m.group(3).strip() if m else ""


def thin_select(sql: str) -> bool:
    proj = projection_clause(sql)
    if not proj:
        return False
    parts = [p.strip() for p in proj.split(",") if p.strip()]
    if EVIDENCE_IN_SELECT.search(proj):
        return len(parts) < 6
    return len(parts) <= 4


def bare_identifier_projection(sql: str) -> bool:
    proj = projection_clause(sql)
    if not proj or EVIDENCE_IN_SELECT.search(proj):
        return False
    parts = [p.strip() for p in proj.split(",") if p.strip()]
    if len(parts) > 4:
        return False
    low = proj.lower()
    return "patient_id" in low


def joined_facts_hidden(query: str, sql: str) -> bool:
    proj = projection_clause(sql)
    low = sql.lower()
    qlow = (query or "").lower()
    tobacco_q = bool(
        re.search(
            r"\b(tobacco|smok|cigarette|nicotine|regular\s+tobacco)\b",
            qlow,
        )
    )
    if tobacco_q and "social_history" in low:
        if not re.search(r"\btobacco_use\b", proj, re.I):
            return True
    if "lab_results" in low:
        if not re.search(r"\b(test_name|result_value)\b", proj, re.I):
            return True
    if "vitals" in low and re.search(r"\bjoin\s+vitals\b|\bvitals\s+\w+\b", low):
        if not re.search(
            r"\b(bp_systolic|bp_diastolic|recorded_date|heart_rate|temperature|"
            r"weight|height|\bbmi\b)\b",
            proj,
            re.I,
        ):
            return True
    if "vitals" in low and re.search(r"\bweight\b", low):
        if not re.search(r"\bweight\b", proj, re.I):
            return True
    if re.search(r"\bdiagnoses\b", low):
        if not re.search(r"\bdiagnosis_name\b", proj, re.I):
            return True
    if "prescriptions" in low:
        if not re.search(r"\b(medication|indication)\b", proj, re.I):
            return True
    if "clinical_notes" in low:
        if not re.search(r"\bnote_text\b", proj, re.I):
            return True
    if "procedures" in low:
        if not re.search(r"\bprocedure_name\b", proj, re.I):
            return True
    if "imaging_results" in low:
        if not re.search(r"\b(imaging_type|findings|imaging_date)\b", proj, re.I):
            return True
    if re.search(r"\bvisits\b", low) and re.search(r"\bhospital\b", low):
        if not re.search(r"\bhospital\b", proj, re.I):
            return True
    return False


def needs_column_enrichment(query: str, sql: str) -> bool:
    if is_population_period_aggregate(sql):
        return False
    if not (CLINICAL_HINT.search(query or "") or CLINICAL_TABLE.search(sql or "")):
        return False
    if joined_facts_hidden(query, sql):
        return True
    if bare_identifier_projection(sql):
        return True
    if thin_select(sql):
        return True
    return False


def clean_sql(sql_text: str | None) -> str:
    if not sql_text:
        return ""
    original = sql_text.strip()
    low = original.lower()
    chunk = original
    if "```sql" in low:
        start = low.index("```sql") + 6
        end = original.find("```", start)
        if end > start:
            chunk = original[start:end]
    elif "```" in original:
        first = original.index("```") + 3
        second = original.find("```", first)
        if second > first:
            chunk = original[first:second]

    chunk = chunk.strip().replace(";", "")
    if chunk:
        return chunk.strip()

    m = re.search(
        r"(?is)\b(WITH\b[\s\S]+?\bSELECT\b[\s\S]+|\bSELECT\b[\s\S]+)",
        original,
    )
    if m:
        return m.group(1).strip().replace(";", "").strip()
    return ""
