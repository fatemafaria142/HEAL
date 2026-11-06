from __future__ import annotations

import json
import os
from typing import Any, Dict

import config
from HEAL.core.llm_factory import create_chat_model
from HEAL.core.prompt_utils import render_prompt_template

from HEAL.agents.self_verifier import AgentSelfVerifier
from HEAL.agents.cav_validator.parsers import parse_structured_verdict
from HEAL.tools.guards.contract_guard import run_deterministic_contract_checks
from HEAL.tools.reliability.disagreement import aggregate_disagreement, compute_disagreement_matrix
from HEAL.tools.reliability.report import build_reliability_report
from HEAL.tools.guards.contract_guard import _collect_contract_text, parse_schema_catalog

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompt.md")


class CrossAgentValidator:
    def __init__(self, model_name=config.OPENAI_MODEL, temperature=0):
        self.model = create_chat_model("cav", model_name=model_name, temperature=temperature)
        self.self_verifier = AgentSelfVerifier(model_name=model_name, temperature=temperature)
        with open(PROMPT_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

    def call(self, state: dict) -> Dict[str, Any]:
        det = run_deterministic_contract_checks(state)
        det_summary = det.summary()

        contracts = _collect_contract_text(state)
        tables, _ = parse_schema_catalog(state.get("schema_summary") or "")
        disagreement_matrix = compute_disagreement_matrix(contracts, tables)
        disagreement_score = aggregate_disagreement(disagreement_matrix)

        self_verify = self.self_verifier.verify_all(state)
        self_verify_failed = [k for k, v in self_verify.items() if not v]

        llm_verdict = None
        llm_consistent = True
        llm_failure_type = None

        run_llm = getattr(config, "HEAL_CROSS_AGENT_VALIDATION", True)
        if det.has_critical and not getattr(config, "HEAL_CAV_LLM_ON_CRITICAL", True):
            run_llm = False

        if run_llm:
            try:
                prompt_text = render_prompt_template(
                    self.prompt_template,
                    {
                        "query": state.get("query") or "",
                        "history_summary": state.get("history_summary")
                        or "No previous history.",
                        "schema_summary": state.get("schema_summary") or "",
                        "schema_vocab": state.get("schema_vocab_snippet")
                        or "_No vocabulary snapshot._",
                        "clinical_plan": state.get("clinical_plan") or "_Missing CIP plan._",
                        "anjt_resolution": state.get("anjt_resolution")
                        or "_Missing HEAL-AT resolution._",
                        "join_nest_plan": state.get("join_nest_plan") or "_Missing HEAL-NJ plan._",
                        "deterministic_findings": det_summary or "_No deterministic issues._",
                        "disagreement_matrix": json.dumps(disagreement_matrix),
                        "self_verification": json.dumps(self_verify),
                    },
                )
                response = self.model.invoke(prompt_text)
                llm_verdict = (response.content or "").strip()
                llm_consistent, _, llm_failure_type = parse_structured_verdict(llm_verdict)
            except Exception as e:
                llm_verdict = f"CAV LLM error: {str(e)[:300]}"
                llm_consistent = not det.has_critical and not self_verify_failed

        passed = (
            not det.has_critical
            and llm_consistent
            and not self_verify_failed
        )

        mitigations = ["retrieval_grounding", "cross_agent_validation"]
        if getattr(config, "HEAL_CAV_SELF_VERIFY", True):
            mitigations.append("self_verification")

        reliability_report = build_reliability_report(
            state,
            cav_passed=passed,
            cav_llm_verdict=llm_verdict,
            self_verification=self_verify,
            mitigations=mitigations,
        )
        reliability_report["disagreement_matrix"] = disagreement_matrix
        reliability_report["disagreement_score"] = disagreement_score
        if llm_failure_type:
            reliability_report["primary_failure_type"] = (
                reliability_report.get("primary_failure_type") or llm_failure_type
            )

        uncertainty = max(
            det.uncertainty_score,
            disagreement_score * 0.5,
            0.25 if self_verify_failed else 0.0,
        )

        if passed:
            trace = (
                f"CAV+: consistent (U={uncertainty:.2f}, D={disagreement_score:.2f}, "
                f"self_verify={self_verify})."
            )
            return {
                "contract_valid": True,
                "contract_validation_feedback": det_summary,
                "contract_uncertainty": uncertainty,
                "reliability_report": reliability_report,
                "disagreement_matrix": disagreement_matrix,
                "error": None,
                "reasoning_trace": state.get("reasoning_trace", []) + [trace],
            }

        feedback_parts = [det_summary]
        if self_verify_failed:
            feedback_parts.append(
                "Self-verification failed for: "
                + ", ".join(self_verify_failed)
                + " — agents may have trusted upstream text over the user query."
            )
        if llm_verdict:
            feedback_parts.append(f"CAV semantic audit:\n{llm_verdict}")
        feedback = "\n\n".join(p for p in feedback_parts if p)

        primary = det.critical_issues[0] if det.critical_issues else None
        if self_verify_failed and not primary:
            err_msg = (
                f"CAV blocked: self-verification failed ({', '.join(self_verify_failed)})"
            )
        elif primary:
            err_msg = f"CAV blocked: {primary.message}"
        else:
            err_msg = "CAV blocked: cross-agent inconsistency detected."

        reliability_report["propagation_prevented"] = True
        reliability_report["cav_passed"] = False

        return {
            "contract_valid": False,
            "contract_validation_feedback": feedback,
            "contract_uncertainty": max(uncertainty, 0.75),
            "reliability_report": reliability_report,
            "disagreement_matrix": disagreement_matrix,
            "error": err_msg,
            "reasoning_trace": state.get("reasoning_trace", [])
            + [f"CAV+: blocked propagation — {err_msg[:120]}"],
        }
