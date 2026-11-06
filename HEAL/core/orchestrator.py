import os
import time
import uuid
from typing import Literal, Any, Dict, Callable, Optional

from sqlalchemy import create_engine, text
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

import config
from database.schema_introspect import (
    compact_clinical_vocab_markdown,
    introspect_schema_markdown,
)
from HEAL.core.state import HEALState, StateTracker
from HEAL.core.social_history_sql import normalize_tobacco_use_sql
from HEAL.tools.guards.sql_guard import validate_read_only_select
from HEAL.agents.cip_planner import ClinicalIntentPlanner
from HEAL.agents.anjt_resolver import AmbiguityTemporalResolver
from HEAL.agents.nj_planner import NestedJoinPathPlanner
from HEAL.agents.s3_synthesizer import SQLSyntaxSynthesizer
from HEAL.agents.dfa_auditor import DualFeedbackAuditor
from HEAL.agents.egr_refiner import ExecutionGuidedRefiner
from HEAL.agents.ebs_summarizer import EvidenceBasedSummarizer
from HEAL.agents.cav_validator import CrossAgentValidator
from HEAL.tools.reliability.report import snapshot_from_state
from HEAL.core.cost_tracker import CostTracker, get_cost_tracker, set_cost_tracker

class HEALOrchestrator:
    def __init__(self):
        self.engine = create_engine(config.DATABASE_URL)
        self.schema_summary = introspect_schema_markdown(self.engine)
        self.schema_vocab_snippet = compact_clinical_vocab_markdown(self.engine)
        self.state_tracker = StateTracker()
        self._checkpointer = MemorySaver()
        self._thread_id = "default"
        
        self.planner = ClinicalIntentPlanner()
        self.anjt_resolver = AmbiguityTemporalResolver()
        self.nj_planner = NestedJoinPathPlanner()
        self.generator = SQLSyntaxSynthesizer()
        self.validator = DualFeedbackAuditor()
        self.refiner = ExecutionGuidedRefiner()
        self.synthesizer = EvidenceBasedSummarizer()
        self.contract_validator = CrossAgentValidator()
        
        self.graph = self._build_graph()

    def refresh_schema(self) -> None:
        self.schema_summary = introspect_schema_markdown(self.engine)
        self.schema_vocab_snippet = compact_clinical_vocab_markdown(self.engine)

    def _maybe_refresh_schema(self) -> None:
        if getattr(config, "HEAL_REFRESH_SCHEMA_EACH_QUERY", False):
            self.refresh_schema()

    def _build_graph(self):
        workflow = StateGraph(HEALState)

        workflow.add_node("plan_intent", self._track_node("plan_intent", self.planner.call))
        workflow.add_node("snapshot_post_cip", self._snapshot_post_cip)
        workflow.add_node("respond_clarification", self.respond_clarification)
        workflow.add_node("respond_cav_clarification", self.respond_cav_clarification)
        workflow.add_node("resolve_anjt", self._track_node("resolve_anjt", self.anjt_resolver.call))
        workflow.add_node("snapshot_post_at", self._snapshot_post_at)
        workflow.add_node("plan_nj", self._track_node("plan_nj", self.nj_planner.call))
        workflow.add_node("snapshot_post_nj", self._snapshot_post_nj)
        workflow.add_node("cross_validate", self._track_node("cross_validate", self._cross_validate_node))
        workflow.add_node("repair_contracts", self._track_node("repair_contracts", self.repair_contracts))
        workflow.add_node("generate_sql", self._track_node("generate_sql", self.generator.call))
        workflow.add_node("validate_sql", self._track_node("validate_sql", self.validator.call))
        workflow.add_node("execute_sql", self._track_node("execute_sql", self.execute_sql_node))
        workflow.add_node("refine_sql", self._track_node("refine_sql", self.refiner.call))
        workflow.add_node("synthesize_response", self._track_node("synthesize_response", self.synthesizer.call))

        workflow.add_edge(START, "plan_intent")
        workflow.add_conditional_edges(
            "plan_intent",
            self._route_after_plan,
            {
                "clarify": "respond_clarification",
                "continue": "snapshot_post_cip",
            },
        )
        workflow.add_edge("respond_clarification", END)
        workflow.add_edge("snapshot_post_cip", "resolve_anjt")
        workflow.add_edge("resolve_anjt", "snapshot_post_at")
        workflow.add_edge("snapshot_post_at", "plan_nj")
        workflow.add_edge("plan_nj", "snapshot_post_nj")
        workflow.add_edge("snapshot_post_nj", "cross_validate")
        workflow.add_conditional_edges(
            "cross_validate",
            self._route_after_cav,
            {
                "continue": "generate_sql",
                "repair": "repair_contracts",
                "clarify": "respond_cav_clarification",
            },
        )
        workflow.add_edge("repair_contracts", "cross_validate")
        workflow.add_edge("respond_cav_clarification", END)
        workflow.add_edge("generate_sql", "validate_sql")
        
        workflow.add_conditional_edges(
            "validate_sql",
            self._check_validation,
            {
                "execute": "execute_sql",
                "refine": "refine_sql"
            }
        )
        
        workflow.add_conditional_edges(
            "execute_sql",
            self._should_continue,
            {
                "refine": "refine_sql",
                "synthesize": "synthesize_response"
            }
        )
        
        workflow.add_edge("refine_sql", "validate_sql")
        workflow.add_edge("synthesize_response", END)

        return workflow.compile(checkpointer=self._checkpointer)

    def set_thread_id(self, thread_id: str) -> None:
        self._thread_id = thread_id or "default"

    def _run_config(self) -> Dict[str, Any]:
        return {"configurable": {"thread_id": self._thread_id}}

    @staticmethod
    def _track_node(node_id: str, fn: Callable) -> Callable:
        def wrapped(state: HEALState):
            t0 = time.perf_counter()
            result = fn(state)
            tracker = get_cost_tracker()
            if tracker:
                tracker.record_node_latency(node_id, (time.perf_counter() - t0) * 1000)
            return result

        return wrapped

    def _begin_cost_tracking(self) -> Optional[CostTracker]:
        if not getattr(config, "HEAL_COST_TRACKING", True):
            set_cost_tracker(None)
            return None
        tracker = CostTracker(model=config.OPENAI_MODEL)
        set_cost_tracker(tracker)
        return tracker

    @staticmethod
    def _end_cost_tracking(tracker: Optional[CostTracker], final_state: HEALState) -> HEALState:
        if tracker:
            tracker.finalize_wall_clock()
            final_state = {**final_state, "cost_report": tracker.to_dict()}
        set_cost_tracker(None)
        return final_state

    @staticmethod
    def _append_snapshot(state: HEALState, stage: str) -> Dict[str, Any]:
        if not getattr(config, "HEAL_RELIABILITY_SNAPSHOTS", True):
            return {}
        snap = snapshot_from_state(state, stage).to_dict()
        existing = list(state.get("reliability_snapshots") or [])
        existing.append(snap)
        return {
            "reliability_snapshots": existing,
            "reasoning_trace": state.get("reasoning_trace", [])
            + [
                f"Reliability snapshot {stage}: "
                f"{snap['issue_count']} issues, U={snap['uncertainty']:.2f}, D={snap['disagreement']:.2f}."
            ],
        }

    def _snapshot_post_cip(self, state: HEALState):
        return self._append_snapshot(state, "post_cip")

    def _snapshot_post_at(self, state: HEALState):
        return self._append_snapshot(state, "post_at")

    def _snapshot_post_nj(self, state: HEALState):
        return self._append_snapshot(state, "post_nj")

    @staticmethod
    def _finalize_reliability(state: HEALState) -> Dict[str, Any]:
        report = dict(state.get("reliability_report") or {})
        if state.get("error") and state.get("sql"):
            report.setdefault("mitigations_applied", [])
            if "dfa_audit" not in report["mitigations_applied"]:
                report["mitigations_applied"] = list(report["mitigations_applied"]) + ["dfa_audit"]
        rc = state.get("refinement_count", 0) or 0
        if rc:
            report["egr_refinement_count"] = rc
            m = list(report.get("mitigations_applied") or [])
            if "execution_guided_repair" not in m:
                m.append("execution_guided_repair")
            report["mitigations_applied"] = m
        if state.get("results") is not None:
            report["execution_completed"] = True
            report["results_count"] = len(state.get("results") or [])
        if state.get("reliability_snapshots"):
            report["stage_snapshots"] = state.get("reliability_snapshots")
        return {"reliability_report": report} if report else {}

    @staticmethod
    def _initial_state(query: str, history_summary: str, schema_summary: str, vocab: str) -> Dict[str, Any]:
        return {
            "query": query,
            "history_summary": history_summary,
            "schema_summary": schema_summary,
            "schema_vocab_snippet": vocab,
            "clinical_plan": None,
            "reasoning_trace": [],
            "sql": None,
            "results": None,
            "error": None,
            "response": None,
            "refinement_count": 0,
            "needs_clarification": False,
            "clarifying_questions": [],
            "anjt_resolution": None,
            "join_nest_plan": None,
            "contract_valid": None,
            "contract_validation_feedback": None,
            "contract_uncertainty": 0.0,
            "contract_repair_count": 0,
            "reliability_report": None,
            "reliability_snapshots": [],
            "disagreement_matrix": {},
            "cost_report": None,
        }

    @staticmethod
    def _route_after_plan(state: HEALState) -> Literal["clarify", "continue"]:
        if state.get("needs_clarification"):
            return "clarify"
        return "continue"

    @staticmethod
    def _route_after_cav(state: HEALState) -> Literal["continue", "repair", "clarify"]:
        if state.get("contract_valid") is False:
            repairs = state.get("contract_repair_count", 0)
            max_repairs = getattr(config, "HEAL_CAV_MAX_REPAIRS", 1)
            if repairs < max_repairs:
                return "repair"
            return "clarify"
        return "continue"

    def _cross_validate_node(self, state: HEALState):
        if not getattr(config, "HEAL_CROSS_AGENT_VALIDATION", True):
            return {
                "contract_valid": True,
                "contract_validation_feedback": None,
                "contract_uncertainty": 0.0,
                "error": None,
                "reasoning_trace": state.get("reasoning_trace", [])
                + ["CAV skipped (HEAL_CROSS_AGENT_VALIDATION=false)."],
            }
        return self.contract_validator.call(state)

    def repair_contracts(self, state: HEALState):
        count = state.get("contract_repair_count", 0)
        at_out = self.anjt_resolver.call(state)
        merged = {**state, **at_out}
        nj_out = self.nj_planner.call(merged)
        trace = state.get("reasoning_trace", []) + [
            f"CAV repair #{count + 1}: replanned HEAL-AT and HEAL-NJ from validation feedback."
        ]
        return {
            **at_out,
            **nj_out,
            "contract_repair_count": count + 1,
            "error": None,
            "reasoning_trace": trace,
        }

    @staticmethod
    def respond_clarification(state: HEALState):
        qs = state.get("clarifying_questions") or []
        if not qs:
            qs = [
                "What cohort and time window should we use (and should dates follow visit vs measurement)?",
                "Do you want distinct patients or every qualifying row?",
            ]
        lines = [
            "Before I run this query on your database, I need a bit more detail:",
            "",
        ]
        for i, q in enumerate(qs, 1):
            lines.append(f"{i}. {q}")
        lines.append("")
        lines.append(
            "Reply with those details and I will generate and execute the appropriate SQL."
        )
        text = "\n".join(lines)
        return {
            "response": text,
            "reasoning_trace": state.get("reasoning_trace", [])
            + ["Paused pipeline: clarification needed before SQL generation."],
            "sql": None,
            "results": None,
            "error": None,
        }

    @staticmethod
    def respond_cav_clarification(state: HEALState):
        feedback = (state.get("contract_validation_feedback") or state.get("error") or "").strip()
        uncertainty = state.get("contract_uncertainty", 0.0)
        lines = [
            "I paused before generating SQL because the planning agents disagreed "
            "or referenced schema objects that could not be verified.",
            "",
            f"Uncertainty signal: {uncertainty:.0%} (higher means more cross-agent disagreement).",
            "",
            "**What went wrong (cross-agent audit):**",
            feedback or "_No detailed feedback available._",
            "",
            "Please rephrase your question with explicit details (cohort, time window, "
            "measurement vs visit dates, and whether you want one row per patient). "
            "This prevents a wrong plan from propagating into SQL.",
        ]
        return {
            "response": "\n".join(lines),
            "reasoning_trace": state.get("reasoning_trace", [])
            + ["Paused pipeline: CAV blocked error propagation after repair attempts."],
            "sql": None,
            "results": None,
            "error": None,
        }

    def _check_validation(self, state: HEALState) -> Literal["execute", "refine"]:
        error = state.get("error")
        refinement_count = state.get("refinement_count", 0)
        
        if error and refinement_count < 3:
            return "refine"
        return "execute"

    def execute_sql_node(self, state: HEALState):
        sql = state.get("sql")
        sql_norm, fixed = normalize_tobacco_use_sql(sql or "", state.get("query"))
        sql = sql_norm
        ok, guard_msg = validate_read_only_select(sql)
        if not ok:
            return {
                "results": None,
                "error": f"Execution skipped: {guard_msg}",
            }
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                columns = result.keys()
                rows = [dict(zip(columns, row)) for row in result.fetchall()]
                out: Dict[str, Any] = {"results": rows, "error": None}
                if fixed:
                    out["sql"] = sql
                return out
        except Exception as e:
            return {"results": None, "error": str(e)}

    def _should_continue(self, state: HEALState) -> Literal["refine", "synthesize"]:
        error = state.get("error")
        results = state.get("results")
        refinement_count = state.get("refinement_count", 0)
        empty_or_missing = results is None or (
            isinstance(results, list) and len(results) == 0
        )
        if (error or empty_or_missing) and refinement_count < 3:
            return "refine"
        return "synthesize"

    def checkpoint_state(self) -> Dict[str, Any]:
        try:
            snap = self.graph.get_state(self._run_config())
            if snap and getattr(snap, "values", None):
                return dict(snap.values)
        except Exception:
            pass
        return {}

    FINAL_EVENT = "__final__"

    def process_query_stream(self, query: str):
        self._maybe_refresh_schema()
        self.set_thread_id(str(uuid.uuid4()))
        history_summary = self.state_tracker.get_history_summary()

        initial_state = self._initial_state(
            query, history_summary, self.schema_summary, self.schema_vocab_snippet
        )

        cfg = self._run_config()
        tracker = self._begin_cost_tracking()
        try:
            for event in self.graph.stream(initial_state, config=cfg):
                for node_name, output in event.items():
                    yield node_name, output
        except Exception:
            set_cost_tracker(None)
            raise

        final_state = self.checkpoint_state()
        final_state.update(self._finalize_reliability(final_state))
        final_state = self._end_cost_tracking(tracker, final_state)
        yield self.FINAL_EVENT, final_state

    def update_history(self, query: str, final_state: HEALState):
        resp = (final_state.get("response") or "").strip()
        excerpt = resp[:600] if resp else ""
        sql = final_state.get("sql")
        clarification_only = sql is None and bool(resp)
        res = final_state.get("results")
        n = len(res) if res is not None else 0
        self.state_tracker.add_turn(
            query,
            sql,
            n,
            response_excerpt=excerpt,
            clarification_only=clarification_only,
        )

    def process_query(self, query: str):
        self._maybe_refresh_schema()
        self.set_thread_id(str(uuid.uuid4()))
        history_summary = self.state_tracker.get_history_summary()
        
        initial_state = self._initial_state(
            query, history_summary, self.schema_summary, self.schema_vocab_snippet
        )

        cfg = self._run_config()
        tracker = self._begin_cost_tracking()
        final_state = self.graph.invoke(initial_state, config=cfg)
        final_state.update(self._finalize_reliability(final_state))
        final_state = self._end_cost_tracking(tracker, final_state)

        self.update_history(query, final_state)
        
        return final_state

    def reset(self):
        self.state_tracker.reset()
