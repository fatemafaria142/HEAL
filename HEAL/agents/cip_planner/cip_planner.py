import json
import os

import config
from HEAL.core.llm_factory import create_chat_model
from langchain_core.prompts import PromptTemplate

from HEAL.agents.cip_planner.parsers import (
    HEAL_JSON_MARKER,
    augment_bare_minimum_clarification,
    augment_clarification_with_rules,
    augment_specificity_gaps,
    merge_after_clarification_pause,
    parse_cip_output,
    sanitize_misleading_clarification_questions,
    strip_placeholder_questions_if_resolved,
    user_resolved_clarification_pair,
)

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class ClinicalIntentPlanner:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("cip", model_name=model_name, temperature=temperature)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def call(self, state: dict):
        query = state.get("query") or ""
        history_summary = state.get("history_summary", "No previous history.")
        merged_query = merge_after_clarification_pause(history_summary, query)
        schema_esc = (state.get("schema_summary") or "").replace("{", "{{").replace(
            "}", "}}"
        )

        try:
            prompt = PromptTemplate.from_template(self.prompt_template)
            chain = prompt | self.model
            response = chain.invoke(
                {
                    "query": merged_query,
                    "history_summary": history_summary,
                    "schema_summary": schema_esc,
                }
            )
            raw = (response.content or "").strip()
        except Exception as e:
            err = str(e)[:400]
            footer = json.dumps(
                {
                    "needs_clarification": True,
                    "questions": [
                        "The clinical planner hit a technical error. Please rephrase your question briefly."
                    ],
                    "intent_type": "retrieve",
                }
            )
            raw = (
                f"### Planner recovery\nCIP model call failed ({err}).\n\n"
                f"{HEAL_JSON_MARKER}\n"
                f"{footer}"
            )

        plan_md, needs_clarification, questions, intent_type = parse_cip_output(raw)

        needs_clarification, questions = strip_placeholder_questions_if_resolved(
            needs_clarification, questions, merged_query
        )

        rules_hit = False
        if getattr(config, "HEAL_CIP_DETERMINISTIC_CLARIFY", True):
            needs_clarification, questions, r1 = augment_clarification_with_rules(
                str(merged_query), needs_clarification, questions
            )
            rules_hit = rules_hit or r1
            needs_clarification, questions, r2 = augment_bare_minimum_clarification(
                str(merged_query), needs_clarification, questions
            )
            rules_hit = rules_hit or r2

        if user_resolved_clarification_pair(merged_query):
            needs_clarification = False
            questions = []

        if getattr(config, "HEAL_CIP_DETERMINISTIC_CLARIFY", True):
            needs_clarification, questions, r3 = augment_specificity_gaps(
                str(merged_query), needs_clarification, questions
            )
            rules_hit = rules_hit or r3

        needs_clarification, questions = sanitize_misleading_clarification_questions(
            str(merged_query), needs_clarification, questions
        )

        reasoning = (
            f"CIP resolved intent_type={intent_type}; clarification="
            f"{'requested' if needs_clarification else 'not needed'}"
        )
        if rules_hit:
            reasoning += (
                "; deterministic clarification rules applied "
                "(optional strict anchor/grain, bare-minimum, location/name gaps)."
            )

        out: dict = {
            "clinical_plan": plan_md,
            "needs_clarification": needs_clarification,
            "clarifying_questions": questions,
            "intent_type": intent_type,
            "reasoning_trace": state.get("reasoning_trace", []) + [reasoning],
        }
        if merged_query.strip() != (query or "").strip():
            out["query"] = merged_query
        return out
