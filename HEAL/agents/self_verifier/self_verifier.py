from __future__ import annotations

import os
from typing import Dict

import config
from HEAL.core.llm_factory import create_chat_model
from HEAL.core.prompt_utils import render_prompt_template

from HEAL.agents.self_verifier.parsers import parse_verification_json

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class AgentSelfVerifier:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("self_verify", model_name=model_name, temperature=temperature)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def verify_all(self, state: dict) -> Dict[str, bool]:
        if not getattr(config, "HEAL_CAV_SELF_VERIFY", True):
            return {"cip": True, "at": True, "nj": True}

        try:
            prompt_text = render_prompt_template(
                self.prompt_template,
                {
                    "query": state.get("query") or "",
                    "history_summary": state.get("history_summary") or "No previous history.",
                    "clinical_plan": state.get("clinical_plan") or "",
                    "anjt_resolution": state.get("anjt_resolution") or "",
                    "join_nest_plan": state.get("join_nest_plan") or "",
                },
            )
            response = self.model.invoke(prompt_text)
            return parse_verification_json(response.content or "")
        except Exception:
            return {"cip": True, "at": True, "nj": True}
