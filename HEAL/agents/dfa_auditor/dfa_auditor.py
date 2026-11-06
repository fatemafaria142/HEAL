import os

import config
from HEAL.core.llm_factory import create_chat_model
from langchain_core.prompts import PromptTemplate

from HEAL.tools.guards.clinical_domain_guard import anemia_hba1c_domain_clash, combined_clinical_intent
from HEAL.tools.reliability.sql_hallucination import ground_sql_from_state
from HEAL.tools.guards.sql_guard import validate_read_only_select

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class DualFeedbackAuditor:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("dfa", model_name=model_name, temperature=0)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def call(self, state: dict):
        sql = state.get("sql")
        query = state.get("query") or ""
        ok, guard_msg = validate_read_only_select(sql)
        if not ok:
            reasoning = f"DFA structural guard: {guard_msg}"
            return {
                "error": f"DFA blocked SQL: {guard_msg}",
                "reasoning_trace": state.get("reasoning_trace", []) + [reasoning],
            }

        if getattr(config, "HEAL_SQL_SCHEMA_GUARD", True):
            grounding = ground_sql_from_state(state, sql)
            if grounding.hallucinated:
                msg = grounding.summary()
                return {
                    "error": f"DFA Audit Failed: SQL references schema objects that do not exist — {msg}",
                    "reasoning_trace": state.get("reasoning_trace", [])
                    + [f"DFA schema grounding: {msg}"],
                }

        if getattr(config, "HEAL_LEGACY_DOMAIN_REGEX", False):
            clash = anemia_hba1c_domain_clash(combined_clinical_intent(state), sql or "")
            if clash:
                reasoning = f"DFA legacy domain regex: {clash[:120]}..."
                return {
                    "error": f"DFA Audit Failed: {clash}",
                    "reasoning_trace": state.get("reasoning_trace", []) + [reasoning],
                }

        plan_raw = state.get("clinical_plan", "No plan provided.")
        plan = (
            plan_raw.replace("{", "{{").replace("}", "}}")
            if isinstance(plan_raw, str)
            else str(plan_raw).replace("{", "{{").replace("}", "}}")
        )
        full_intent_esc = combined_clinical_intent(state).replace("{", "{{").replace(
            "}", "}}"
        )
        vocab_raw = state.get("schema_vocab_snippet") or ""
        schema_vocab_esc = vocab_raw.replace("{", "{{").replace("}", "}}")

        try:
            prompt = PromptTemplate.from_template(self.prompt_template)
            chain = prompt | self.model
            response = chain.invoke(
                {
                    "sql": sql,
                    "query": (query or "").replace("{", "{{").replace("}", "}}"),
                    "plan": plan,
                    "full_intent": full_intent_esc or "_None._",
                    "schema_vocab": schema_vocab_esc or "_No vocabulary snapshot._",
                }
            )
            feedback = (response.content or "").strip()
        except Exception as e:
            return {
                "error": f"DFA auditor model error: {str(e)[:300]}",
                "reasoning_trace": state.get("reasoning_trace", [])
                + [f"DFA LLM call failed: {str(e)[:80]}"],
            }

        reasoning = f"DFA performed audit: {feedback[:100]}..."

        fu = feedback.upper().strip()
        first_line = fu.split("\n", 1)[0].strip()
        if first_line.startswith("INVALID") or "NOT VALID" in first_line[:20]:
            is_valid = False
        elif first_line.startswith("VALID"):
            is_valid = True
        else:
            is_valid = "VALID" in first_line and "INVALID" not in first_line
        
        if is_valid:
            return {
                "error": None,
                "reasoning_trace": state.get("reasoning_trace", []) + [reasoning]
            }
        else:
            return {
                "error": f"DFA Audit Failed: {feedback}",
                "reasoning_trace": state.get("reasoning_trace", []) + [reasoning]
            }
