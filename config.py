import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.getenv("HEAL_OUTPUT_DIR", os.path.join(BASE_DIR, "output"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Create a .env file (see .env.example) or export "
        "DATABASE_URL, e.g. postgresql://<user>:<password>@localhost:5432/<db>."
    )

HEAL_REFRESH_SCHEMA_EACH_QUERY = os.getenv("HEAL_REFRESH_SCHEMA_EACH_QUERY", "").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_CIP_DETERMINISTIC_CLARIFY = os.getenv("HEAL_CIP_DETERMINISTIC_CLARIFY", "true").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_CIP_STRICT_INTERVIEWER = os.getenv("HEAL_CIP_STRICT_INTERVIEWER", "false").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_LEGACY_DOMAIN_REGEX = os.getenv("HEAL_LEGACY_DOMAIN_REGEX", "false").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_CROSS_AGENT_VALIDATION = os.getenv("HEAL_CROSS_AGENT_VALIDATION", "true").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_CAV_LLM_ON_CRITICAL = os.getenv("HEAL_CAV_LLM_ON_CRITICAL", "true").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_CAV_MAX_REPAIRS = int(os.getenv("HEAL_CAV_MAX_REPAIRS", "1"))

HEAL_CAV_SELF_VERIFY = os.getenv("HEAL_CAV_SELF_VERIFY", "true").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_SQL_SCHEMA_GUARD = os.getenv("HEAL_SQL_SCHEMA_GUARD", "true").lower() in (
    "1",
    "true",
    "yes",
)

HEAL_RELIABILITY_SNAPSHOTS = os.getenv("HEAL_RELIABILITY_SNAPSHOTS", "true").lower() in (
    "1",
    "true",
    "yes",
)


if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_TEMPERATURE = 0.0

# Prices are USD per 1M tokens, matching the three backbones evaluated in the paper
# (Results-Tables.tex); keep in sync with pricing_for_model()'s fallback in cost_tracker.py.
LLM_PRICING = {
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00,
    },
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
    },
    "gpt-5-mini": {
        "input": 0.25,
        "output": 2.00,
    },
    "gpt-5-nano": {
        "input": 0.05,
        "output": 0.40,
    },
}

HEAL_COST_TRACKING = os.getenv("HEAL_COST_TRACKING", "true").lower() in (
    "1",
    "true",
    "yes",
)

