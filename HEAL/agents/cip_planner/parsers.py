import json
import re

import config

HEAL_JSON_MARKER = "---HEAL_JSON---"

ANCHOR_CLARIFICATION_QUESTION = (
    "Should the time window apply to the **measurement date** "
    "(e.g. `vitals.recorded_date`, `lab_results.test_date`) "
    "or to the **visit / encounter date** (`visits.visit_date`)? "
    "These usually align but can differ and change which rows qualify."
)

GRAIN_CLARIFICATION_QUESTION = (
    "Do you want **one row per patient** (distinct patients who had at least one qualifying reading in the window) "
    "or **every qualifying measurement row** (possibly multiple rows per patient)?"
)

_MEASUREMENT_CTX = re.compile(
    r"\b(vitals?\b|blood\s+pressure|\bbp\b|systolic|diastolic|heart\s+rate|pulse|temperature|"
    r"spo2|labs?\b|lab\s+results?\b|hba1c|creatinine|glucose|cholesterol|ldl)\b",
    re.I,
)
_RELATIVE_TIME_CTX = re.compile(
    r"\b(last|past|recent|today|yesterday|this\s+week|this\s+month|this\s+year|since|within|rolling|trailing)\b|"
    r"\d+\s*(day|week|month|year)s?\b|"
    r"(days?|weeks?|months?|years?)\s+ago",
    re.I,
)
_EXPLICIT_DATE_ANCHOR = re.compile(
    r"(visit\s+date|encounter\s+date|appointment\s+date|clinic\s+date|"
    r"recorded\s+date|measurement\s+date|reading\s+date|test\s+date|lab\s+date|"
    r"date\s+of\s+(the\s+)?(visit|encounter|reading|measurement|lab))",
    re.I,
)
_GRAIN_ALREADY_CLEAR = re.compile(
    r"\b(distinct|each\s+reading|every\s+reading|all\s+readings|one\s+row\s+per|per\s+reading|"
    r"every\s+measurement|each\s+vital|per\s+patient|one\s+row\s+per\s+patient)\b",
    re.I,
)
_GRAIN_APPLICABLE = re.compile(r"\b(patients?\b|how\s+many|list\s+(the\s+)?patients?)\b", re.I)

_ALL_TIME = re.compile(
    r"\ball\s+time\b|\bentire\s+(history|period|database)?\b|\bno\s+time\s+(limit|filter|restriction)\b|"
    r"\bfrom\s+(the\s+)?beginning\b|\blifetime\b|\beverything\b",
    re.I,
)
_PER_PATIENT_GRAIN = re.compile(
    r"\b(per\s+patient|one\s+row\s+per\s+patient|distinct\s+patients?|each\s+patient|"
    r"one\s+per\s+patient)\b",
    re.I,
)

_ULTRA_VAGUE_ONLY = re.compile(
    r"^\s*(hi|hello|hey|hiya|test|help|thanks?|thank\s+you|ok|okay|data|info|query|result|yes|no)\s*[!?.]?\s*$",
    re.I,
)
_STRONG_QUERY_ANCHOR = re.compile(
    r"\b(visit|diagnos|icd|lab|vital|med|drug|prescri|admission|discharge|"
    r"hba1c|a1c|glucose|bp\b|systolic|diastolic|creatinine|bun|ldl|cholesterol|"
    r"smok|tobacco|alcohol|diabet|hypertens|asthma|copd|stroke|mi\b|chf|"
    r"infection|sepsis|fever|pneumonia|anemi|pregnan|icu|er\b|emergency|"
    r"age\b|gender|male|female|death|readmit|"
    r"how\s+many|count\b|average|mean|trend|compare|"
    r"last\s+\d+|past\s+\d+|\d+\s*(day|week|month|year)s?|"
    r"\ball\s+time\b|this\s+year|last\s+year|"
    r"this\s+week|last\s+week|this\s+month|last\s+month|"
    r"today|yesterday)\b",
    re.I,
)

BARE_MINIMUM_CLARIFICATION_QUESTIONS = (
    "What **clinical or operational criterion** should define this cohort (e.g. diagnosis, lab "
    "threshold, medication, visit or admit rule)?",
    "What should the output be: a **patient list**, **row-level detail**, or **counts/summary**?",
)

_LOCATION_TRIGGER = re.compile(
    r"\b(which\s+(?:hospital|site|facility|clinic|ward|unit|branch|location|area|region)|"
    r"geographic|from\s+what\s+(?:city|area)|in\s+what\s+(?:city|region)|"
    r"at\s+which\s+(?:hospital|site|facility|clinic))\b",
    re.I,
)
_CAPITALIZED_PLACE_FRAGMENT = re.compile(
    r"\b(?:in|at|from|near)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b"
)

_NAME_TRIGGER = re.compile(
    r"\b(?:patient\s+(?:named|called)|which\s+patient|that\s+patient|"
    r"find\s+patient\s+by\s+name|provider\s+named|doctor\s+named)\b",
    re.I,
)

LOCATION_SPECIFICITY_QUESTION = (
    "Which **location or site** should we use (facility, city, region, ward), and what **exact** "
    "value or spelling should we match in the data?"
)

NAME_SPECIFICITY_QUESTION = (
    "What is the **exact patient or provider name** (spelling) or identifier (e.g. MRN) to search?"
)

_ALLOWED_INTENTS = frozenset({"retrieve", "aggregate", "compare", "trend", "explain"})

_CLARIFY_WHEN_NO_JSON_META = {
    "needs_clarification": True,
    "questions": [
        "What should we retrieve (e.g. patient list, counts, trends) and over what time frame?",
        "Which clinical domain applies (diagnoses, labs, vitals, meds, visits)?",
    ],
    "intent_type": "retrieve",
}


def _needs_location_specificity_question(q: str) -> bool:
    if not _LOCATION_TRIGGER.search(q):
        return False
    if _CAPITALIZED_PLACE_FRAGMENT.search(q):
        return False
    if re.search(r'["\'][^"\']{2,}["\']', q):
        return False
    return True


def _needs_name_specificity_question(q: str) -> bool:
    if not _NAME_TRIGGER.search(q):
        return False
    if re.search(r"\b(?:named|called)\s+[A-Za-z][a-z]+\b", q):
        return False
    if re.search(r'["\'][^"\']{2,}["\']', q):
        return False
    if re.search(r"\bDr\.?\s+[A-Z][a-z]+\b", q):
        return False
    return True


def augment_specificity_gaps(
    query: str, needs_clarification: bool, questions: list[str]
) -> tuple[bool, list[str], bool]:
    qs = list(questions)
    blob = " ".join(qs).lower()
    applied = False

    def _missing_location(blob_lc: str) -> bool:
        return "location or site" not in blob_lc

    def _missing_name(blob_lc: str) -> bool:
        return not any(x in blob_lc for x in ("exact patient or provider name", "identifier"))

    if _needs_location_specificity_question(query) and _missing_location(blob):
        needs_clarification = True
        qs.append(LOCATION_SPECIFICITY_QUESTION)
        applied = True
        blob = " ".join(qs).lower()

    if _needs_name_specificity_question(query) and _missing_name(blob):
        needs_clarification = True
        qs.append(NAME_SPECIFICITY_QUESTION)
        applied = True

    qs = _dedupe_questions(qs)
    if len(qs) > 3:
        qs = qs[:3]
    return needs_clarification, qs, applied


def sanitize_misleading_clarification_questions(
    query: str, needs_clarification: bool, questions: list[str]
) -> tuple[bool, list[str]]:
    q = str(query or "")
    qs = [str(x).strip() for x in (questions or []) if str(x).strip()]

    if not _needs_location_specificity_question(q):
        qs = [x for x in qs if "location or site" not in x.lower()]

    if not _needs_name_specificity_question(q):
        qs = [
            x
            for x in qs
            if "exact patient or provider name" not in x.lower()
            and x != NAME_SPECIFICITY_QUESTION
        ]

    qs = _dedupe_questions(qs)
    if not qs:
        return False, []
    return True, qs


def merge_after_clarification_pause(history_summary: str, query: str) -> str:
    if not query or not str(query).strip():
        return query
    if not history_summary or "Pipeline paused for clarification" not in history_summary:
        return query
    users = re.findall(r"Turn\s+\d+\s+.{1,3}USER:\s*(.+)", history_summary)
    if not users:
        return query
    base = users[-1].strip()
    q = query.strip()
    if q.lower() == base.lower() or not base:
        return query
    return f"{base}\n\n[Follow-up from clinician: {q}]"


def _user_supplied_time_window(q: str) -> bool:
    if _ALL_TIME.search(q):
        return True
    if _EXPLICIT_DATE_ANCHOR.search(q):
        return True
    if _RELATIVE_TIME_CTX.search(q):
        return True
    if re.search(r"\b\d+\s*(day|week|month|year)s?\b", q, re.I):
        return True
    if re.search(r"\b(since|before|after|between|from)\s+\d{4}", q, re.I):
        return True
    return False


def _user_supplied_grain(q: str) -> bool:
    if _GRAIN_ALREADY_CLEAR.search(q):
        return True
    if _PER_PATIENT_GRAIN.search(q):
        return True
    if re.search(r"\b(per\s+visit|each\s+visit|every\s+visit|aggregate|count\s+only)\b", q, re.I):
        return True
    return False


def user_resolved_clarification_pair(q: str) -> bool:
    return _user_supplied_time_window(q) and _user_supplied_grain(q)


def _needs_anchor_clarification(query: str) -> bool:
    if not query or not str(query).strip():
        return False
    if _ALL_TIME.search(query):
        return False
    if _EXPLICIT_DATE_ANCHOR.search(query):
        return False
    if not (_MEASUREMENT_CTX.search(query) and _RELATIVE_TIME_CTX.search(query)):
        return False
    return True


def _needs_grain_clarification(query: str) -> bool:
    if _GRAIN_ALREADY_CLEAR.search(query):
        return False
    if _PER_PATIENT_GRAIN.search(query):
        return False
    if not _GRAIN_APPLICABLE.search(query):
        return False
    return _needs_anchor_clarification(query)


def _questions_already_cover_anchor(questions: list[str]) -> bool:
    blob = " ".join(questions).lower()
    has_visit = "visit" in blob and ("date" in blob or "encounter" in blob)
    has_measurement = any(
        x in blob for x in ("recorded", "measurement", "reading", "test date", "lab date")
    )
    return has_visit and has_measurement


def _questions_already_cover_grain(questions: list[str]) -> bool:
    blob = " ".join(questions).lower()
    return ("distinct" in blob or "per patient" in blob or "multiple rows" in blob) and (
        "reading" in blob or "row" in blob or "measurement" in blob
    )


def _needs_bare_minimum_clarification(query: str) -> bool:
    q = (query or "").strip()
    if not q:
        return True
    if _ULTRA_VAGUE_ONLY.match(q):
        return True
    words = q.split()
    if len(words) <= 4 and not _STRONG_QUERY_ANCHOR.search(q):
        return True
    return False


def _dedupe_questions(questions: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for q in questions:
        key = q.strip().lower()[:200]
        if key and key not in seen:
            seen.add(key)
            out.append(q.strip())
    return out


def augment_clarification_with_rules(
    query: str, needs_clarification: bool, questions: list[str]
) -> tuple[bool, list[str], bool]:
    if not getattr(config, "HEAL_CIP_STRICT_INTERVIEWER", False):
        return needs_clarification, questions, False

    qs = list(questions)
    applied = False

    if _needs_anchor_clarification(query) and not _questions_already_cover_anchor(qs):
        needs_clarification = True
        qs.append(ANCHOR_CLARIFICATION_QUESTION)
        applied = True

    if _needs_grain_clarification(query) and not _questions_already_cover_grain(qs):
        needs_clarification = True
        qs.append(GRAIN_CLARIFICATION_QUESTION)
        applied = True

    return needs_clarification, _dedupe_questions(qs), applied


def augment_bare_minimum_clarification(
    query: str, needs_clarification: bool, questions: list[str]
) -> tuple[bool, list[str], bool]:
    if not _needs_bare_minimum_clarification(query):
        return needs_clarification, questions, False
    qs = list(questions)
    blob = " ".join(qs).lower()
    for bq in BARE_MINIMUM_CLARIFICATION_QUESTIONS:
        if bq[:50].lower() not in blob and bq.lower() not in blob:
            qs.append(bq)
    return True, _dedupe_questions(qs), True


def _fallback_meta_from_fragment(fragment: str) -> dict:
    meta: dict = {}
    if not fragment:
        return meta
    m = re.search(r'"needs_clarification"\s*:\s*(true|false)', fragment, re.I)
    if m:
        meta["needs_clarification"] = m.group(1).lower() == "true"
    m2 = re.search(r'"intent_type"\s*:\s*"([^"]+)"', fragment)
    if m2:
        meta["intent_type"] = m2.group(1).strip()
    return meta


def parse_cip_output(content: str) -> tuple[str, bool, list[str], str]:
    text = (content or "").strip()
    if HEAL_JSON_MARKER in text:
        md_part, json_part = text.split(HEAL_JSON_MARKER, 1)
        md_part = md_part.strip()
        jp = json_part.strip()
        meta: dict = {}
        try:
            meta = json.loads(jp)
        except json.JSONDecodeError:
            meta = _fallback_meta_from_fragment(jp)
            if not meta and jp:
                brace = jp.find("{")
                if brace >= 0:
                    for end in range(len(jp), brace, -1):
                        try:
                            meta = json.loads(jp[brace:end])
                            break
                        except json.JSONDecodeError:
                            continue
            if not meta:
                meta = _fallback_meta_from_fragment(text)
    else:
        md_part = text
        meta = _fallback_meta_from_fragment(text)

    if not meta:
        meta = dict(_CLARIFY_WHEN_NO_JSON_META)

    needs = bool(meta.get("needs_clarification", False))
    questions = meta.get("questions") or []
    if not isinstance(questions, list):
        questions = [str(questions)]
    questions = [str(q).strip() for q in questions if str(q).strip()]
    intent_type = str(meta.get("intent_type", "retrieve")).strip() or "retrieve"
    if intent_type not in _ALLOWED_INTENTS:
        intent_type = "retrieve"

    if needs and not questions:
        questions = [
            "Could you specify the time window (e.g. last 30 days, this year, or all time)?",
            "Should results be listed per patient, per visit, or as a single count or aggregate?",
        ]

    return md_part, needs, questions, intent_type


def strip_placeholder_questions_if_resolved(
    needs: bool, questions: list[str], merged_query: str
) -> tuple[bool, list[str]]:
    if needs and user_resolved_clarification_pair(merged_query):
        return False, []
    return needs, questions
