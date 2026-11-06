import os

import config
from HEAL.core.llm_factory import create_chat_model
from langchain_core.prompts import PromptTemplate

from HEAL.core.social_history_sql import normalize_tobacco_use_sql
from HEAL.agents.egr_refiner.parsers import extract_sql

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class ExecutionGuidedRefiner:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("egr", model_name=model_name, temperature=temperature)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def call(self, state: dict):
        failed_sql = state.get("sql") or ""
        err = state.get("error")
        results = state.get("results")
        if err:
            error_message = err
        elif isinstance(results, list) and len(results) == 0:
            error_message = (
                "Query executed successfully but returned **0 rows**. "
                "Likely causes: exact-match (`=`) on text that differs from stored values; "
                "missing synonyms (trade vs generic names, abbreviations); overly narrow "
                "`ILIKE` patterns; tight date windows; wrong join grain; or filters on "
                "columns that use different coded labels than the user's words. Prefer "
                "`ILIKE '%core_term%'` with **OR** across synonyms, broader diagnosis/lab/"
                "medication patterns, or relaxed dates while preserving clinical intent."
            )
        else:
            error_message = err or "Unknown error"
        refinement_count = state.get("refinement_count", 0) + 1
        plan_raw = state.get("clinical_plan", "No plan provided.")
        plan_esc = (
            plan_raw.replace("{", "{{").replace("}", "}}")
            if isinstance(plan_raw, str)
            else str(plan_raw).replace("{", "{{").replace("}", "}}")
        )
        schema_esc = (state.get("schema_summary") or "").replace("{", "{{").replace(
            "}", "}}"
        )

        try:
            prompt = PromptTemplate.from_template(self.prompt_template)
            chain = prompt | self.model
            response = chain.invoke(
                {
                    "failed_sql": failed_sql,
                    "error_message": error_message,
                    "clinical_plan": plan_esc,
                    "user_query": state.get("query", ""),
                    "schema_summary": schema_esc,
                }
            )
            raw = response.content or ""
        except Exception as e:
            raw = ""
            error_message = f"{error_message} | EGR model failure: {str(e)[:200]}"

        sql = extract_sql(raw) if raw.strip() else failed_sql.strip()
        sql, _ = normalize_tobacco_use_sql(sql, state.get("query"))
        error_display = f"{error_message[:50]}..." if error_message else "Unknown execution error"
        reasoning = f"EGR performed healing attempt {refinement_count} based on feedback: {error_display}"

        return {
            "sql": sql,
            "refinement_count": refinement_count,
            "error": None,
            "reasoning_trace": state.get("reasoning_trace", []) + [reasoning]
        }
