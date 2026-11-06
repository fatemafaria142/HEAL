import os

import config
from HEAL.core.llm_factory import create_chat_model
from langchain_core.prompts import PromptTemplate

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class AmbiguityTemporalResolver:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("at", model_name=model_name, temperature=temperature)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def call(self, state: dict):
        query = state["query"]
        history = state.get("history_summary", "No previous history.")
        plan_raw = state.get("clinical_plan") or "No plan provided."
        intent = state.get("intent_type") or "retrieve"
        plan_esc = (
            plan_raw.replace("{", "{{").replace("}", "}}")
            if isinstance(plan_raw, str)
            else str(plan_raw).replace("{", "{{").replace("}", "}}")
        )
        schema_esc = (state.get("schema_summary") or "").replace("{", "{{").replace(
            "}", "}}"
        )

        repair_fb = (state.get("contract_validation_feedback") or "").strip()
        if repair_fb:
            plan_esc = (
                plan_esc
                + "\n\n### CAV repair feedback (fix contradictions — do not repeat prior mistakes)\n"
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
                    "intent_type": intent,
                    "schema_summary": schema_esc,
                }
            )
            text = (response.content or "").strip()
            reasoning = "HEAL-AT locked ambiguity mappings and temporal anchors for A/T."
        except Exception as e:
            text = (
                "### HEAL-AT fallback\n"
                f"Resolver error ({str(e)[:300]}). Default: map clinical terms to schema columns; "
                "use `recorded_date` for vitals windows unless visit-centric wording."
            )
            reasoning = f"HEAL-AT degraded: {str(e)[:80]}"

        return {
            "anjt_resolution": text,
            "reasoning_trace": state.get("reasoning_trace", []) + [reasoning],
        }
