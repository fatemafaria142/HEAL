import uuid
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
from HEAL.core.orchestrator import HEALOrchestrator

RESEARCH_TITLE = (
    "HEAL: A Context-Aware Self-Correcting Conversational Multi-Agent Framework "
    "for Text-to-SQL on Clinical Patient Records"
)
SHORT_SUBTITLE = "Schema-grounded natural language → PostgreSQL for structured clinical analytics"

st.set_page_config(
    page_title="HEAL · Clinical Text-to-SQL Research Demo",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
    html, body, [class*="css"] { font-family: 'DM Sans', system-ui, sans-serif; }
    .block-container { padding-top: 0.75rem; max-width: 1100px; }
    .main {
        background: linear-gradient(165deg, #eff6ff 0%, #fffbeb 42%, #f0f9ff 100%);
    }
    /* Hero — compact + light blue / yellow */
    .heal-hero {
        background: linear-gradient(120deg, #dbeafe 0%, #fef9c3 48%, #bae6fd 100%);
        color: #0f172a;
        padding: 0.65rem 1rem 0.6rem;
        border-radius: 12px;
        margin-bottom: 0.65rem;
        border: 1px solid #93c5fd;
        box-shadow: 0 6px 18px -8px rgba(37, 99, 235, 0.2);
    }
    .heal-hero h1 {
        font-size: clamp(0.82rem, 1.2vw, 1.02rem);
        font-weight: 700;
        line-height: 1.3;
        margin: 0 0 0.35rem 0;
        letter-spacing: -0.015em;
        color: #1e3a8a;
    }
    .heal-hero p {
        margin: 0;
        font-size: 0.78rem;
        color: #475569;
        line-height: 1.35;
    }
    .heal-badge {
        display: inline-block;
        background: #fef08a;
        color: #854d0e;
        padding: 0.12rem 0.45rem;
        border-radius: 999px;
        font-size: 0.62rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
        border: 1px solid #fde047;
    }
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #ffffff 0%, #eff6ff 100%);
        border-right: 1px solid #bfdbfe;
    }
    .sidebar-brand {
        padding: 0.5rem 0 1rem;
        border-bottom: 1px solid #e2e8f0;
        margin-bottom: 1rem;
    }
    .sidebar-brand .sb-title {
        font-weight: 700;
        font-size: 1.05rem;
        color: #1e40af;
        margin: 0 0 0.35rem 0;
    }
    .sidebar-brand .sb-sub {
        font-size: 0.78rem;
        color: #64748b;
        line-height: 1.4;
        margin: 0;
    }
    /* Chat & status */
    .stChatMessage { border-radius: 14px; }
    .stStatus { border-radius: 12px; border: 1px solid #cbd5e1; }
    div[data-testid="stExpander"] details {
        border-radius: 10px;
        border: 1px solid #e2e8f0;
        background: #ffffffcc;
    }
    /* Dataframe container */
    div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
    /* Chat input polish */
    .stChatInput textarea {
        font-family: 'DM Sans', sans-serif !important;
        border-radius: 12px !important;
    }
    /* Code blocks */
    .stCodeBlock { border-radius: 10px; }
    code, pre { font-family: 'JetBrains Mono', monospace !important; }
</style>
""",
    unsafe_allow_html=True,
)

_PAIR_LABELS = {
    "cip_at": "CIP ↔ HEAL-AT",
    "cip_nj": "CIP ↔ HEAL-NJ",
    "at_nj": "HEAL-AT ↔ HEAL-NJ",
}
_STAGE_LABELS = {"post_cip": "R₁ · after CIP", "post_at": "R₂ · after AT", "post_nj": "R₃ · after NJ"}


def render_reliability(report: Optional[Dict[str, Any]], uncertainty: Optional[float] = None) -> None:
    if not report:
        return

    passed = report.get("cav_passed", True)
    label = "CAV+ passed" if passed else "CAV+ blocked"
    with st.expander(f"Reliability — {label}", expanded=not passed):
        u = report.get("uncertainty_score", uncertainty or 0.0)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Verdict", "Pass" if passed else "Blocked")
        c2.metric("Uncertainty", f"{u:.2f}")
        c3.metric("Disagreement", f"{report.get('disagreement_score', 0.0):.2f}")
        c4.metric("Propagation risk", f"{report.get('propagation_risk', 0.0):.2f}")

        if not passed:
            st.warning(
                "The planning contract was stopped **before SQL synthesis**. "
                "No query reached the database."
            )

        sv = report.get("self_verification") or {}
        if sv:
            marks = "  ".join(
                f"{'✅' if ok else '❌'} `{agent}`" for agent, ok in sv.items()
            )
            st.markdown(f"**Self-verification** (against your original question) — {marks}")

        matrix = report.get("disagreement_matrix") or {}
        if matrix:
            st.markdown("**Pairwise disagreement** — rule-computed, not LLM-scored")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Agent pair": _PAIR_LABELS.get(k, k), "Score": v}
                        for k, v in matrix.items()
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

        issues = report.get("issues") or []
        if issues:
            st.markdown(f"**Issues detected — {len(issues)}**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Severity": i.get("severity"),
                            "Type": i.get("failure_type"),
                            "Stage": i.get("stage") or i.get("source"),
                            "Message": i.get("message"),
                        }
                        for i in issues
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No deterministic issues raised against the planning contract.")

        snaps = report.get("stage_snapshots") or []
        if snaps:
            st.markdown("**Staged snapshots** — where problems first appear")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Stage": _STAGE_LABELS.get(s.get("stage"), s.get("stage")),
                            "Issues": s.get("issue_count"),
                            "Critical": s.get("critical_count"),
                            "Uncertainty": s.get("uncertainty"),
                            "Disagreement": s.get("disagreement"),
                        }
                        for s in snaps
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

        bits = []
        if report.get("primary_failure_type"):
            bits.append(f"primary failure: `{report['primary_failure_type']}`")
        if report.get("failure_stage"):
            bits.append(f"stage: `{report['failure_stage']}`")
        if report.get("repair_attempted"):
            bits.append(
                f"contract repair: {'succeeded' if report.get('repair_succeeded') else 'attempted'}"
            )
        if report.get("egr_refinement_count"):
            bits.append(f"EGR refinements: {report['egr_refinement_count']}")
        if report.get("mitigations_applied"):
            bits.append("mitigations: " + ", ".join(f"`{m}`" for m in report["mitigations_applied"]))
        if bits:
            st.caption(" · ".join(bits))

        verdict = report.get("cav_llm_verdict")
        if verdict:
            with st.expander("CAV semantic audit (raw)", expanded=False):
                st.markdown(verdict)


def render_cost(cost_report: Optional[Dict[str, Any]]) -> None:
    if not cost_report:
        return

    with st.expander("Cost & latency", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Cost", f"${cost_report.get('total_cost_usd', 0):.4f}")
        c2.metric("Tokens", f"{cost_report.get('total_tokens', 0):,}")
        c3.metric("LLM calls", cost_report.get("llm_call_count", 0))
        c4.metric("Wall clock", f"{cost_report.get('wall_clock_ms', 0) / 1000:.1f}s")

        by_agent = cost_report.get("by_agent") or {}
        if by_agent:
            rows = [
                {
                    "Agent": stats.get("agent_id", aid),
                    "Calls": stats.get("llm_calls", 0),
                    "Input tokens": stats.get("input_tokens", 0),
                    "Output tokens": stats.get("output_tokens", 0),
                    "Cost (USD)": stats.get("cost_usd", 0.0),
                    "Latency (ms)": stats.get("latency_ms", 0.0),
                }
                for aid, stats in by_agent.items()
            ]
            rows.sort(key=lambda r: r["Cost (USD)"], reverse=True)
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        pricing = cost_report.get("pricing_per_1m_tokens_usd") or {}
        if pricing:
            st.caption(
                f"Model `{cost_report.get('model')}` · "
                f"${pricing.get('input')} in / ${pricing.get('output')} out per 1M tokens"
            )


if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = HEALOrchestrator()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "heal_thread_id" not in st.session_state:
    st.session_state.heal_thread_id = str(uuid.uuid4())
st.session_state.orchestrator.set_thread_id(st.session_state.heal_thread_id)

with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="sb-title">◆ HEAL</div>
            <p class="sb-sub">Multi-agent text-to-SQL over structured patient data</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Research title", expanded=False):
        st.caption(RESEARCH_TITLE)
    st.markdown("---")
    st.subheader("System status")
    if st.session_state.orchestrator.engine:
        st.success("PostgreSQL connected")
    else:
        st.error("Database offline — check `DATABASE_URL`")
    if st.button("Clear conversation", width="stretch"):
        st.session_state.messages = []
        st.session_state.heal_thread_id = str(uuid.uuid4())
        st.session_state.orchestrator.reset()
        st.session_state.orchestrator.set_thread_id(st.session_state.heal_thread_id)
        st.rerun()

st.markdown(
    f"""
    <div class="heal-hero">
        <span class="heal-badge">Research demo</span>
        <h1>{RESEARCH_TITLE}</h1>
        <p>{SHORT_SUBTITLE}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant" and message.get("user_question"):
            st.markdown(f"**Your question:** {message['user_question']}")
        st.markdown(message["content"])
        if "sql" in message:
            c1, c2 = st.columns(2)
            with c1:
                with st.expander("Clinical plan (CIP)"):
                    st.markdown(message.get("plan", "No plan available."))
            with c2:
                with st.expander("Generated SQL (S3)"):
                    st.code(message["sql"], language="sql")
            if message.get("anjt"):
                with st.expander("HEAL-AT — ambiguity & temporal"):
                    st.markdown(message["anjt"])
            if message.get("nj"):
                with st.expander("HEAL-NJ — nested & join-path"):
                    st.markdown(message["nj"])
            if "reasoning" in message:
                with st.expander("Full reasoning trace", expanded=False):
                    for i, trace in enumerate(message["reasoning"], 1):
                        st.markdown(f"**{i}.** {trace}")
        if message["role"] == "assistant":
            render_reliability(message.get("reliability"), message.get("uncertainty", 0.0))
            render_cost(message.get("cost"))
        if "results" in message and message["results"]:
            st.dataframe(pd.DataFrame(message["results"]), width="stretch")

user_query = st.chat_input("Ask a clinical question in natural language…")

if user_query:
    st.session_state.messages.append({"role": "user", "content": user_query})
    with st.chat_message("user"):
        st.markdown(user_query)

    with st.chat_message("assistant"):
        final_response = ""
        final_sql = ""
        final_plan = ""
        final_traces = []
        final_anjt = ""
        final_nj = ""
        final_results = None
        final_reliability: Optional[Dict[str, Any]] = None
        final_cost: Optional[Dict[str, Any]] = None
        final_uncertainty = 0.0
        pipeline_error: Optional[Exception] = None
        accumulated_state: Dict[str, Any] = {}

        with st.status("HEAL pipeline running…", expanded=True) as status:
            orchestrator = st.session_state.orchestrator
            try:
                for node, state in orchestrator.process_query_stream(user_query):
                    accumulated_state.update(state)

                    if node == "plan_intent":
                        st.write("**Clinical Intent Planner (CIP)** — deconstructing the query…")
                        if "clinical_plan" in state:
                            st.markdown(state["clinical_plan"])
                        if state.get("needs_clarification"):
                            st.info("Clarification requested before SQL generation.")
                    elif node == "respond_clarification":
                        st.write("**Awaiting clarification** (SQL not run yet).")
                        if state.get("response"):
                            final_response = state["response"]
                    elif node == "resolve_anjt":
                        st.write("**HEAL-AT** — ambiguity (A) & temporal logic (T)…")
                        if state.get("anjt_resolution"):
                            with st.expander("HEAL-AT output (this step)", expanded=True):
                                st.markdown(state["anjt_resolution"])
                    elif node == "plan_nj":
                        st.write("**HEAL-NJ** — nested queries (N) & join paths (J)…")
                        if state.get("join_nest_plan"):
                            with st.expander("HEAL-NJ output (this step)", expanded=True):
                                st.markdown(state["join_nest_plan"])
                    elif node in ("snapshot_post_cip", "snapshot_post_at", "snapshot_post_nj"):
                        snaps = state.get("reliability_snapshots") or []
                        if snaps:
                            s = snaps[-1]
                            st.write(
                                f"**Reliability snapshot** `{s.get('stage')}` — "
                                f"{s.get('issue_count', 0)} issue(s), "
                                f"{s.get('critical_count', 0)} critical, "
                                f"U={s.get('uncertainty', 0):.2f}, D={s.get('disagreement', 0):.2f}"
                            )
                    elif node == "cross_validate":
                        st.write("**HEAL-CAV+** — cross-agent validation before SQL…")
                        if state.get("contract_valid"):
                            st.success(
                                f"Planning contract consistent "
                                f"(uncertainty {state.get('contract_uncertainty', 0):.2f})."
                            )
                        else:
                            st.error(
                                f"CAV+ blocked the contract — {state.get('error', 'inconsistent plans')}"
                            )
                    elif node == "repair_contracts":
                        st.write(
                            f"**Contract repair** — replanning HEAL-AT + HEAL-NJ from CAV feedback "
                            f"(attempt {state.get('contract_repair_count', 1)})…"
                        )
                    elif node == "respond_cav_clarification":
                        st.warning(
                            "CAV+ could not reconcile the planning agents. Stopping before SQL "
                            "rather than running a query that may be wrong."
                        )
                        if state.get("response"):
                            final_response = state["response"]
                    elif node == "generate_sql":
                        st.write("**Semantic SQL Synthesizer (S3)** — crafting SQL…")
                        if state.get("sql"):
                            with st.expander("Draft SQL (this step)", expanded=False):
                                st.code(state["sql"], language="sql")
                    elif node == "validate_sql":
                        st.write("**Dual-Feedback Auditor (DFA)** — verifying logic…")
                        if state.get("error"):
                            st.warning(f"DFA note: {state['error']}")
                    elif node == "execute_sql":
                        st.write("**Execution** — querying PostgreSQL…")
                        if state.get("error"):
                            st.error(f"Execution error: {state['error']}")
                        if accumulated_state.get("sql"):
                            final_sql = accumulated_state["sql"]
                        if "results" in accumulated_state:
                            final_results = accumulated_state["results"]
                    elif node == "refine_sql":
                        st.write(
                            f"**Execution-Guided Refiner (EGR)** — healing SQL "
                            f"(attempt {accumulated_state.get('refinement_count', 0)})…"
                        )
                    elif node == "synthesize_response":
                        st.write("**Evidence-Based Summarizer (EBS)** — drafting the answer…")
                        if accumulated_state.get("response"):
                            final_response = accumulated_state["response"]

                    if accumulated_state.get("clinical_plan") is not None:
                        final_plan = accumulated_state["clinical_plan"]
                    if accumulated_state.get("reasoning_trace"):
                        final_traces = accumulated_state["reasoning_trace"]

            except Exception as e:
                pipeline_error = e
                st.exception(e)

            if pipeline_error is None:
                status.update(
                    label="Done",
                    state="complete",
                    expanded=False,
                )
            else:
                status.update(label="Pipeline failed", state="error", expanded=True)

        if accumulated_state:
            final_response = (accumulated_state.get("response") or final_response or "").strip()
            final_sql = accumulated_state.get("sql") or final_sql or ""
            final_plan = accumulated_state.get("clinical_plan") or final_plan
            final_traces = accumulated_state.get("reasoning_trace") or final_traces
            final_anjt = accumulated_state.get("anjt_resolution") or final_anjt
            final_nj = accumulated_state.get("join_nest_plan") or final_nj
            res = accumulated_state.get("results")
            if res is not None:
                final_results = res
            final_reliability = accumulated_state.get("reliability_report") or final_reliability
            final_cost = accumulated_state.get("cost_report") or final_cost
            final_uncertainty = accumulated_state.get("contract_uncertainty") or final_uncertainty

        st.markdown(f"**Your question:** {user_query}")
        if pipeline_error:
            st.error("The pipeline stopped with an error (see details in the status block above).")
        elif final_response:
            st.markdown(final_response)
        else:
            st.warning(
                "No assistant response was produced. Check **OPENAI_API_KEY** in `.env`, network access, "
                "and that PostgreSQL is reachable at **DATABASE_URL**."
            )

        col1, col2 = st.columns(2)
        with col1:
            if final_plan:
                with st.expander("Clinical Intent Plan (CIP)", expanded=False):
                    st.markdown(final_plan)
        with col2:
            if final_sql:
                with st.expander("Generated SQL (S3)", expanded=False):
                    st.code(final_sql, language="sql")

        if final_anjt:
            with st.expander("HEAL-AT — ambiguity & temporal (full)", expanded=False):
                st.markdown(final_anjt)
        if final_nj:
            with st.expander("HEAL-NJ — nested & join-path plan (full)", expanded=False):
                st.markdown(final_nj)
        if final_traces:
            with st.expander("Full reasoning trace (all agents)", expanded=True):
                for i, trace in enumerate(final_traces, 1):
                    st.markdown(f"**{i}.** {trace}")

        render_reliability(final_reliability, final_uncertainty)
        render_cost(final_cost)

        if final_results is not None:
            st.write(f"**Matching records:** {len(final_results)}")
            if len(final_results) == 0:
                st.caption("Empty result set for this query.")
            else:
                st.dataframe(pd.DataFrame(final_results), width="stretch")

        out_text = final_response
        if pipeline_error and not out_text:
            out_text = f"*Error:* `{pipeline_error}`"
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": out_text or "No output.",
                "user_question": user_query,
                "sql": final_sql,
                "plan": final_plan,
                "anjt": final_anjt,
                "nj": final_nj,
                "reasoning": final_traces,
                "results": final_results,
                "reliability": final_reliability,
                "cost": final_cost,
                "uncertainty": final_uncertainty,
            }
        )

        if pipeline_error is None and accumulated_state:
            st.session_state.orchestrator.update_history(user_query, accumulated_state)

st.markdown(
    """
    <div style="text-align:center; color:#64748b; font-size:0.75rem; padding:1.25rem 0 0.35rem;">
        HEAL research prototype · Text-to-SQL with validation & refinement
    </div>
    """,
    unsafe_allow_html=True,
)
