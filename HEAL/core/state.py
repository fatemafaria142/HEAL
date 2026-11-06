from typing import TypedDict, List, Optional, Dict

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired


class HEALState(TypedDict):
    query: str
    history_summary: str
    schema_summary: str
    schema_vocab_snippet: str
    clinical_plan: Optional[str]
    reasoning_trace: List[str]
    sql: Optional[str]
    results: Optional[List[Dict]]
    error: Optional[str]
    response: Optional[str]
    refinement_count: int
    needs_clarification: NotRequired[bool]
    clarifying_questions: NotRequired[List[str]]
    intent_type: NotRequired[str]
    anjt_resolution: NotRequired[Optional[str]]
    join_nest_plan: NotRequired[Optional[str]]
    contract_valid: NotRequired[Optional[bool]]
    contract_validation_feedback: NotRequired[Optional[str]]
    contract_uncertainty: NotRequired[float]
    contract_repair_count: NotRequired[int]
    reliability_report: NotRequired[Optional[Dict]]
    reliability_snapshots: NotRequired[List[Dict]]
    disagreement_matrix: NotRequired[Dict[str, float]]
    cost_report: NotRequired[Optional[Dict]]


class StateTracker:
    MAX_TURNS = 24

    def __init__(self):
        self.history: List[Dict] = []

    def add_turn(
        self,
        query: str,
        sql: Optional[str],
        result_count: int,
        *,
        response_excerpt: str = "",
        clarification_only: bool = False,
    ):
        self.history.append(
            {
                "query": query,
                "sql": sql,
                "result_count": result_count,
                "response_excerpt": (response_excerpt or "")[:600],
                "clarification_only": clarification_only,
            }
        )
        if len(self.history) > self.MAX_TURNS:
            self.history = self.history[-self.MAX_TURNS :]

    def get_history_summary(self) -> str:
        if not self.history:
            return "No previous history."

        lines: List[str] = []
        for i, turn in enumerate(self.history):
            lines.append(f"Turn {i + 1} — USER: {turn['query']}")
            if turn.get("clarification_only"):
                lines.append(
                    "  → Pipeline paused for clarification (no SQL executed). Assistant asked follow-ups."
                )
                if turn.get("response_excerpt"):
                    lines.append(
                        f"  → Assistant excerpt: {turn['response_excerpt'][:280]}..."
                    )
                lines.append("")
                continue
            lines.append(f"  → SQL executed: {turn.get('sql')}")
            lines.append(f"  → Rows returned: {turn['result_count']}")
            if turn.get("response_excerpt"):
                lines.append(
                    f"  → Answer excerpt (for coreference): {turn['response_excerpt'][:280]}..."
                )
            lines.append("")
        return "\n".join(lines).strip()

    def reset(self):
        self.history = []
