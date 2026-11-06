from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import config

_tracker_ctx: ContextVar[Optional["CostTracker"]] = ContextVar("heal_cost_tracker", default=None)


def get_cost_tracker() -> Optional["CostTracker"]:
    return _tracker_ctx.get()


def set_cost_tracker(tracker: Optional["CostTracker"]) -> None:
    _tracker_ctx.set(tracker)


def pricing_for_model(model: str) -> Dict[str, float]:
    table = getattr(config, "LLM_PRICING", {})
    if model in table:
        return table[model]
    for known, prices in table.items():
        if model.startswith(known):
            return prices
    raise KeyError(
        f"No pricing entry for model '{model}' in config.LLM_PRICING; "
        "add one instead of silently billing at another model's rate."
    )


def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Dict[str, float]:
    p = pricing_for_model(model)
    input_cost = input_tokens * p["input"] / 1_000_000
    output_cost = output_tokens * p["output"] / 1_000_000
    return {
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(input_cost + output_cost, 6),
    }


@dataclass
class LLMCallRecord:
    agent_id: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost_usd": self.input_cost_usd,
            "output_cost_usd": self.output_cost_usd,
            "total_cost_usd": self.total_cost_usd,
        }


@dataclass
class CostTracker:
    model: str = field(default_factory=lambda: config.OPENAI_MODEL)
    _calls: List[LLMCallRecord] = field(default_factory=list)
    _node_latency_ms: Dict[str, float] = field(default_factory=dict)
    _wall_clock_ms: float = 0.0
    _started_at: float = field(default_factory=time.perf_counter)

    def record_llm(
        self,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        *,
        model: Optional[str] = None,
    ) -> None:
        model = model or self.model
        costs = compute_cost_usd(model, input_tokens, output_tokens)
        self._calls.append(
            LLMCallRecord(
                agent_id=agent_id,
                model=model,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                total_tokens=int(input_tokens) + int(output_tokens),
                input_cost_usd=costs["input_cost_usd"],
                output_cost_usd=costs["output_cost_usd"],
                total_cost_usd=costs["total_cost_usd"],
            )
        )

    def record_from_message(self, agent_id: str, message: Any, *, model: Optional[str] = None) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        if not usage and hasattr(message, "response_metadata"):
            meta = message.response_metadata or {}
            usage = meta.get("token_usage") or meta.get("usage") or {}
        input_t = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_t = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        if input_t or output_t:
            self.record_llm(agent_id, input_t, output_t, model=model or self.model)

    def record_node_latency(self, node_id: str, latency_ms: float) -> None:
        self._node_latency_ms[node_id] = self._node_latency_ms.get(node_id, 0.0) + latency_ms

    def finalize_wall_clock(self) -> None:
        self._wall_clock_ms = (time.perf_counter() - self._started_at) * 1000

    def _by_agent(self) -> Dict[str, Dict[str, Any]]:
        agg: Dict[str, Dict[str, Any]] = {}
        for call in self._calls:
            bucket = agg.setdefault(
                call.agent_id,
                {
                    "agent_id": call.agent_id,
                    "llm_calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                },
            )
            bucket["llm_calls"] += 1
            bucket["input_tokens"] += call.input_tokens
            bucket["output_tokens"] += call.output_tokens
            bucket["total_tokens"] += call.total_tokens
            bucket["cost_usd"] = round(bucket["cost_usd"] + call.total_cost_usd, 6)
        for node_id, ms in self._node_latency_ms.items():
            agent = _NODE_TO_AGENT.get(node_id, node_id)
            if agent in agg:
                agg[agent]["latency_ms"] = round(ms, 2)
            else:
                agg.setdefault(agent, {"agent_id": agent, "latency_ms": round(ms, 2)})
        for a in agg.values():
            a["cost_usd"] = round(a.get("cost_usd", 0.0), 6)
        return agg

    def to_dict(self) -> Dict[str, Any]:
        total_in = sum(c.input_tokens for c in self._calls)
        total_out = sum(c.output_tokens for c in self._calls)
        total_cost = sum(c.total_cost_usd for c in self._calls)
        try:
            pricing = pricing_for_model(self.model)
        except KeyError as e:
            # Display-only field; the summed total_cost_usd above is unaffected since
            # each call was already priced (or skipped with a warning) in record_llm.
            print(f"[cost_tracker] {e}")
            pricing = None
        return {
            "model": self.model,
            "pricing_per_1m_tokens_usd": pricing,
            "llm_call_count": len(self._calls),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "total_cost_usd": round(total_cost, 6),
            "wall_clock_ms": round(self._wall_clock_ms, 2),
            "by_agent": self._by_agent(),
            "by_node_latency_ms": {k: round(v, 2) for k, v in self._node_latency_ms.items()},
            "llm_calls": [c.to_dict() for c in self._calls],
        }


_NODE_TO_AGENT = {
    "plan_intent": "cip",
    "resolve_anjt": "at",
    "plan_nj": "nj",
    "cross_validate": "cav",
    "generate_sql": "s3",
    "validate_sql": "dfa",
    "refine_sql": "egr",
    "synthesize_response": "ebs",
    "repair_contracts": "contract_repair",
    "snapshot_post_cip": "telemetry",
    "snapshot_post_at": "telemetry",
    "snapshot_post_nj": "telemetry",
}
