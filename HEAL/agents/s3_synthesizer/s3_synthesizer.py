import os
import re

import config
from HEAL.core.llm_factory import create_chat_model
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate

from HEAL.core.social_history_sql import normalize_tobacco_use_sql
from HEAL.tools.guards.sql_guard import validate_read_only_select
from HEAL.agents.s3_synthesizer.parsers import (
    EVIDENCE_IN_SELECT,
    clean_sql,
    needs_column_enrichment,
    projection_clause,
)

AGENT_DIR = os.path.dirname(__file__)
SQL_GEN_PROMPT_PATH = os.path.join(AGENT_DIR, "sql_gen.md")
SQL_ENRICH_PROMPT_PATH = os.path.join(AGENT_DIR, "sql_enrich.md")


class SQLSyntaxSynthesizer:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("s3", model_name=model_name, temperature=temperature)
        with open(SQL_GEN_PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()
        with open(SQL_ENRICH_PROMPT_PATH, "r", encoding="utf-8") as f:
            self._enrich_instruction = f.read()

    def call(self, state: dict):
        query = state.get("query") or ""
        history = state.get("history_summary") or "No previous history."
        plan_raw = state.get("clinical_plan", "No plan provided.")
        intent = state.get("intent_type") or "retrieve"
        anjt_raw = state.get("anjt_resolution") or ""
        nj_raw = state.get("join_nest_plan") or ""
        plan_str = plan_raw if isinstance(plan_raw, str) else str(plan_raw)
        plan_escaped = plan_str.replace("{", "{{").replace("}", "}}")
        anjt_esc = (
            anjt_raw.replace("{", "{{").replace("}", "}}")
            if isinstance(anjt_raw, str)
            else str(anjt_raw).replace("{", "{{").replace("}", "}}")
        )
        nj_esc = (
            nj_raw.replace("{", "{{").replace("}", "}}")
            if isinstance(nj_raw, str)
            else str(nj_raw).replace("{", "{{").replace("}", "}}")
        )
        schema_esc = (state.get("schema_summary") or "").replace("{", "{{").replace(
            "}", "}}"
        )

        augmented_prompt = (
            "### CIP intent_type (match SQL shape to this): "
            + str(intent)
            + "\n### Guidance from Clinical Intent Planner (CIP):\n"
            + plan_escaped
            + "\n### HEAL-AT — Ambiguity & Temporal (A, T):\n"
            + anjt_esc
            + "\n### HEAL-NJ — Nested & Join-Path (N, J):\n"
            + nj_esc
            + "\n---\n"
            + self.prompt_template
        )

        traces = list(state.get("reasoning_trace") or [])

        try:
            prompt = PromptTemplate.from_template(augmented_prompt)
            chain = prompt | self.model
            response = chain.invoke(
                {"query": query, "history": history, "schema_summary": schema_esc}
            )
            raw = response.content or ""
        except Exception as e:
            err = str(e)[:400]
            return {
                "sql": "",
                "reasoning_trace": traces + [f"S3 model invocation failed: {err}"],
            }

        sql = clean_sql(raw)
        traces.append(
            f"S3 synthesized SQL (intent_type={intent}) using CIP + HEAL-AT + HEAL-NJ."
        )

        enriched, enrich_note = self._maybe_enrich_select(query, sql, intent)
        if enrich_note:
            traces.append(enrich_note)
        sql = enriched

        sql, tobacco_fix = normalize_tobacco_use_sql(sql, query)
        if tobacco_fix:
            traces.append(
                "Deterministic fix: tobacco_use literal `regular` → `Current` (matches DB categories)."
            )

        return {"sql": sql, "reasoning_trace": traces}

    def _maybe_enrich_select(self, query: str, sql: str, intent: str) -> tuple[str, str]:
        if not sql.strip():
            return sql, ""
        if intent == "aggregate" and re.search(
            r"(?is)^\s*select\s+count\b", sql.strip()
        ):
            return sql, ""
        if re.search(r"(?is)^\s*select\s+count\b", sql.strip()) and re.search(
            r"\bhow\s+many\b", query.lower()
        ):
            return sql, ""

        if not needs_column_enrichment(query, sql):
            return sql, ""

        body = (
            self._enrich_instruction.replace("{query}", query.strip())
            .replace("{sql}", sql.strip())
        )
        try:
            response = self.model.invoke([HumanMessage(content=body)])
            raw = response.content or ""
        except Exception as e:
            return sql, f"S3b enrich skipped (API error): {str(e)[:120]}"

        candidate = clean_sql(raw)
        ok, msg = validate_read_only_select(candidate)
        if not ok:
            return sql, f"S3b enrich rejected ({msg}); kept original SQL."
        proj_old = projection_clause(sql)
        proj_new = projection_clause(candidate)
        had_evidence = bool(EVIDENCE_IN_SELECT.search(proj_old))
        has_evidence = bool(EVIDENCE_IN_SELECT.search(proj_new))
        if has_evidence and not had_evidence:
            return candidate, "S3b enrichment pass added interpretability columns to SELECT."
        if len(candidate) > len(sql) + 12 and has_evidence:
            return candidate, "S3b enrichment pass expanded SELECT for transparency."
        return sql, ""
