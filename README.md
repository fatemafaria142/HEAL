# HEAL

**A Multi-Agent Framework with Disagreement-Gated Validation for Reliable Text-to-SQL on Clinical Patient Records**

HEAL turns clinicians' natural-language questions into read-only PostgreSQL queries over patient records. A LangGraph pipeline of specialised LLM agents plans the query, resolves ambiguity and temporal anchors, designs join paths, and then **cross-validates the agents against each other before any SQL is written**. When the planners disagree or reference schema objects that do not exist, HEAL repairs the plan or asks the user to clarify instead of propagating the error into SQL.

## Pipeline

```
User query
  └─► CIP  Clinical Intent Planner ──(underspecified)──► clarifying questions
        └─► HEAL-AT  Ambiguity & Temporal resolver
              └─► HEAL-NJ  Nested & Join-path planner
                    └─► CAV  Cross-Agent Validator ──(fail)──► repair AT/NJ ──(still fails)──► clarify
                          └─► S3   SQL Syntax Synthesizer
                                └─► DFA  Dual-Feedback Auditor ⇄ EGR  Execution-Guided Refiner (≤3)
                                      └─► Execute (read-only) ⇄ EGR
                                            └─► EBS  Evidence-Based Summarizer ─► answer
```

| Agent | Path | Role |
|---|---|---|
| CIP | `HEAL/agents/cip_planner` | Classifies intent, drafts a clinical plan, and requests clarification (LLM + deterministic rules). |
| HEAL-AT | `HEAL/agents/anjt_resolver` | Maps clinical terms to schema columns and fixes temporal anchors (visit vs. measurement dates). |
| HEAL-NJ | `HEAL/agents/nj_planner` | Plans join paths, grain, and nested/CTE structure. |
| CAV | `HEAL/agents/cav_validator` | Disagreement-gated validation: deterministic contract checks, pairwise disagreement matrix, per-agent self-verification, and an LLM semantic audit. |
| Self-verifier | `HEAL/agents/self_verifier` | Checks that each planner stayed faithful to the user query (used by CAV). |
| S3 | `HEAL/agents/s3_synthesizer` | Generates SQL, with an optional enrichment pass that adds interpretability columns. |
| DFA | `HEAL/agents/dfa_auditor` | Read-only guard, schema-grounding (hallucinated table/column detection), and an LLM audit. |
| EGR | `HEAL/agents/egr_refiner` | Repairs SQL from audit failures, execution errors, or empty results. |
| EBS | `HEAL/agents/ebs_summarizer` | Writes the final answer grounded in returned rows. |

Every run also produces a **reliability report** (per-stage snapshots, failure taxonomy: retrieval / reasoning / memory / tool-use, uncertainty and disagreement scores) and a **cost report** (tokens, USD, and latency per agent).

## Repository layout

```
HEAL/
├── core/                  # orchestrator (LangGraph), state, LLM factory, cost tracking
├── agents/                # one folder per agent: <agent>.py, prompt.md, parsers.py
└── tools/
    ├── guards/            # read-only SQL, contract, and clinical-domain guards
    └── reliability/       # taxonomy, disagreement, SQL hallucination, reports
database/                  # SQLAlchemy models, schema introspection, SynClin-SQL fixture
automatic_evaluation/      # LLM judge, hallucination, reliability, and cost metrics
error_analysis/            # LLM-based failure-category attribution
human_evaluation/          # annotation task preparation and agreement statistics
test/                      # batch / single-query runner and test queries
app.py                     # Streamlit UI
heal_pipeline.py           # interactive CLI
config.py                  # environment-driven settings and feature flags
```

## Requirements

- Python 3.10+
- PostgreSQL
- An OpenAI API key

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then set OPENAI_API_KEY and DATABASE_URL
```

Load the synthetic **SynClin-SQL** database (11 tables, 100 synthetic patients). This **drops and recreates** all HEAL tables in the target database:

```bash
python database/import_db.py
```

To regenerate the fixture from the seeder, run `python -m database.build_fixture`. The CSV exports are in `database/fixtures/csv/`.

## Usage

**Web UI**

```bash
streamlit run app.py
```

**CLI**

```bash
python heal_pipeline.py
```

Type `reset` to clear the conversation history, or `exit` to quit.

**Programmatic**

```python
from HEAL.core.orchestrator import HEALOrchestrator

heal = HEALOrchestrator()
state = heal.process_query("How many patients have an HbA1c above 7?")
print(state["sql"], state["response"], state["reliability_report"], state["cost_report"])
```

## Configuration

Settings are read from `.env` (see `.env.example` and `config.py`).

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | — | Required. |
| `DATABASE_URL` | — | Required. PostgreSQL connection string. |
| `OPENAI_MODEL` | `gpt-5-mini` | Backbone model; must have an entry in `config.LLM_PRICING`. |
| `HEAL_OUTPUT_DIR` | `output` | Output directory used by `config.OUTPUT_DIR`. The evaluation scripts write to `output/` at the repository root. |
| `HEAL_CROSS_AGENT_VALIDATION` | `true` | Enable CAV. |
| `HEAL_CAV_LLM_ON_CRITICAL` | `true` | Run the CAV LLM audit even when deterministic checks already failed. |
| `HEAL_CAV_MAX_REPAIRS` | `1` | AT/NJ repair attempts before asking for clarification. |
| `HEAL_CAV_SELF_VERIFY` | `true` | Enable per-agent self-verification. |
| `HEAL_SQL_SCHEMA_GUARD` | `true` | Reject SQL referencing unknown tables/columns. |
| `HEAL_CIP_DETERMINISTIC_CLARIFY` | `true` | Rule-based clarification in CIP. |
| `HEAL_CIP_STRICT_INTERVIEWER` | `false` | Stricter clarification policy. |
| `HEAL_LEGACY_DOMAIN_REGEX` | `false` | Legacy regex domain-clash check in DFA. |
| `HEAL_REFRESH_SCHEMA_EACH_QUERY` | `false` | Re-introspect the schema before every query. |
| `HEAL_RELIABILITY_SNAPSHOTS` | `true` | Record per-stage reliability snapshots. |
| `HEAL_COST_TRACKING` | `true` | Record token usage, cost, and latency. |

The flags make it straightforward to run ablations, e.g. `HEAL_CROSS_AGENT_VALIDATION=false`.

## Evaluation

Run these from the repository root. Outputs are written to `output/`.

```bash
# 1. Generate predictions for test/test_queries.json -> output/run_results.json
python test/run_generate.py                    # --resume, --input <file.json>
python test/run_generate.py --query "..." --gold-sql "..."   # single ad hoc query

# 2. Automatic metrics
python automatic_evaluation/llm_judge.py              # -> output/llm_judge_result/
python automatic_evaluation/hallucination_metrics.py  # -> output/hallucination_metrics/
python automatic_evaluation/reliability_metrics.py    # -> output/reliability_metrics/
python automatic_evaluation/cost_metrics.py           # -> output/cost_metrics/

# 3. Error analysis (uses the LLM judge output)
python error_analysis/analyzer.py                     # -> output/error_analysis/

# 4. Human evaluation
python human_evaluation/prepare_task.py   # -> human_evaluation/human_annotation_task.csv
python human_evaluation/human_stats.py    # agreement statistics after annotation
```

Test queries use the format `{"query_id": "...", "question": "...", "gold_sql": "..."}`.

## Data and privacy

The bundled data is fully synthetic. HEAL sends schema samples (including column values) and up to five result rows to the configured LLM provider. Do not connect it to a database with real patient data unless your provider agreement and deployment comply with the applicable regulations (e.g., HIPAA). Generated SQL is restricted to single `SELECT`/`WITH` statements, but you should also use a database role with read-only permissions.

## License

Apache License 2.0. See [LICENSE](LICENSE).

