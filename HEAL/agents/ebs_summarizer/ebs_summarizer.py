import os

import config
from HEAL.core.llm_factory import create_chat_model
from langchain_core.prompts import PromptTemplate

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class EvidenceBasedSummarizer:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0.7):
        self.model = create_chat_model("ebs", model_name=model_name, temperature=temperature)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def call(self, state: dict):
        query = state.get("query") or ""
        sql = state.get("sql") or "N/A"
        results = state.get("results") or []
        history_summary = state.get("history_summary", "No previous history.")

        prompt = PromptTemplate.from_template(self.prompt_template)
        chain = prompt | self.model

        results_sample = results[:5] if results else "No records found."

        try:
            response = chain.invoke(
                {
                    "history_summary": history_summary,
                    "query": query,
                    "sql": sql,
                    "count": len(results) if results else 0,
                    "results_sample": str(results_sample),
                }
            )
            body = (response.content or "").strip()
            if not body:
                n = len(results) if results else 0
                body = (
                    f"**Summary**\nThe query completed and returned **{n}** row(s). "
                    "The narrative model returned an empty message; use the result table and SQL for details."
                )
            reasoning = "EBS synthesized final clinical narrative grounded in database records."
        except Exception as e:
            n = len(results) if results else 0
            body = (
                f"**Summary (fallback)**\nQuery completed with **{n}** row(s) returned. "
                f"The narrative generator failed ({str(e)[:200]}). "
                "Review the result table and SQL above."
            )
            reasoning = f"EBS degraded: {str(e)[:80]}"

        return {
            "response": body,
            "reasoning_trace": state.get("reasoning_trace", []) + [reasoning],
        }
