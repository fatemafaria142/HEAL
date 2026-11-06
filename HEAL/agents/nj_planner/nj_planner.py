import os

import config
from HEAL.core.llm_factory import create_chat_model
from langchain_core.prompts import PromptTemplate

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class NestedJoinPathPlanner:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("nj", model_name=model_name, temperature=temperature)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def call(self, state: dict):
        query = state["query"]
        history = state.get("history_summary", "No previous history.")
        plan_raw = state.get("clinical_plan") or "No plan provided."
        anjt_raw = state.get("anjt_resolution") or "Not available."
        intent = state.get("intent_type") or "retrieve"

        plan_esc = (
            plan_raw.replace("{", "{{").replace("}", "}}")
            if isinstance(plan_raw, str)
            else str(plan_raw).replace("{", "{{").replace("}", "}}")
        )
        anjt_esc = (
            anjt_raw.replace("{", "{{").replace("}", "}}")
            if isinstance(anjt_raw, str)
            else str(anjt_raw).replace("{", "{{").replace("}", "}}")
        )
        schema_esc = (state.get("schema_summary") or "").replace("{", "{{").replace(
            "}", "}}"
        )

        repair_fb = (state.get("contract_validation_feedback") or "").strip()
        if repair_fb:
            anjt_esc = (
                anjt_esc
                + "\n\n### CAV repair feedback (align join/nest plan — fix contradictions)\n"
                + repair_fb.replace("{", "{{").replace("}", "}}")
            )

        try:
            prompt = PromptTemplate.from_template(self.prompt_template)
            chain = prompt | self.model
            response = chain.invoke(
                {
                    "query": query,
                    "history_summary": history,
                    "clinical_plan": plan_esc,
                    "anjt_resolution": anjt_esc,
                    "intent_type": intent,
                    "schema_summary": schema_esc,
                }
            )
            text = (response.content or "").strip()
            reasoning = "HEAL-NJ defined join paths and nested-query strategy for N/J."
        except Exception as e:
            text = (
                "### HEAL-NJ fallback\n"
                f"Planner error ({str(e)[:300]}). Default: join via `patient_id`; "
                "use `visit_id` when the question is encounter-specific."
            )
            reasoning = f"HEAL-NJ degraded: {str(e)[:80]}"

        return {
            "join_nest_plan": text,
            "reasoning_trace": state.get("reasoning_trace", []) + [reasoning],
        }
