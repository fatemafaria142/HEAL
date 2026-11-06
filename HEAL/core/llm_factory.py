from __future__ import annotations

from typing import Any, List, Optional

import config
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from HEAL.core.cost_tracker import get_cost_tracker


class HEALLLMUsageCallback(BaseCallbackHandler):
    def __init__(self, agent_id: str, model_name: str):
        self.agent_id = agent_id
        self.model_name = model_name

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        tracker = get_cost_tracker()
        if not tracker:
            return
        for gen_list in response.generations:
            for gen in gen_list:
                msg = gen.message
                usage = getattr(msg, "usage_metadata", None) or {}
                if not usage and hasattr(msg, "response_metadata"):
                    meta = msg.response_metadata or {}
                    usage = meta.get("token_usage") or meta.get("usage") or {}
                input_t = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
                output_t = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
                if input_t or output_t:
                    try:
                        tracker.record_llm(
                            self.agent_id,
                            input_t,
                            output_t,
                            model=self.model_name,
                        )
                    except KeyError as e:
                        # Missing price entry for this model: skip cost recording for this
                        # call rather than crashing the pipeline mid-conversation.
                        print(f"[cost_tracker] {e}")


def create_chat_model(
    agent_id: str,
    *,
    model_name: Optional[str] = None,
    temperature: Optional[float] = None,
) -> ChatOpenAI:
    model = model_name or config.OPENAI_MODEL
    temp = config.OPENAI_TEMPERATURE if temperature is None else temperature
    callbacks: List[BaseCallbackHandler] = [HEALLLMUsageCallback(agent_id, model)]
    return ChatOpenAI(model=model, temperature=temp, callbacks=callbacks)
