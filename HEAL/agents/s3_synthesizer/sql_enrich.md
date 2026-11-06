### HEAL-S3b — SELECT enrichment (clinical transparency)

**Default mission:** For **every** user query whose SQL returns **detail rows** (not a single population statistic), expand the **`SELECT`** until the result set is **reader-complete**: someone opening the table should see **all facts that the SQL used** to include each row—**for every question type**, not only vitals or weight.

The first-pass SQL often stops at `patient_id`, `name`; your job is to **repair** that into an evidence-complete list whenever this pass runs.

### Tree of thought (enrich or pass-through)

1. Is it **`SELECT COUNT`** only for a **how many** question (scalar count)? → **Return SQL unchanged**.
2. Is it **`DATE_TRUNC` + aggregate** with **no patient id** (population / cohort time-series only)? → **Return unchanged** (do not add patients or break one-row-per-period).
3. Otherwise (lists, joins, per-patient rows): → **Enrich** per the task rules until predicates and clinical facts are visible.
4. Would a new **`JOIN`** **change** who is included? → **Do not add** that join; only expose columns from tables **already** in the query (or lift subquery outputs into the outer SELECT).

### Few-shot decisions

| SQL pattern | Action |
|-------------|--------|
| `SELECT COUNT(DISTINCT patient_id) …` | **Unchanged** |
| `SELECT DATE_TRUNC('month', …), AVG(bp_systolic) … GROUP BY 1` | **Unchanged** |
| `SELECT p.patient_id, p.name FROM … JOIN lab_results …` missing `test_name`, `result_value` | **Enrich SELECT** with lab columns |

### User question
{query}

### Current SQL (PostgreSQL, snake_case — single statement below)

{sql}

### Task
Rewrite into **one** read-only `SELECT` (or `WITH … SELECT`) that:

1. **Keeps** the same clinical cohort: preserve `WHERE` filters, joins, and time windows unless a join is **required** only to expose columns already implied by the question.
2. **Expands** the SELECT list so each row shows **why** it matched — **evidence-complete** for **all** domains: include **every fact-table column** the cohort logic uses (filters, thresholds, time windows, joins), not only `patient_id` and `name`:
   - **`lab_results`**: `test_name`, `result_value`, `unit`, `test_date`, `flag`, `reference_range` when present in query or needed to explain a threshold.
   - **`vitals`**: `bp_systolic`, `bp_diastolic`, `recorded_date`, `weight`, `height`, `bmi`, `heart_rate`, `temperature`, `vital_id` / `visit_id` as needed for any filter or tie-break.
   - **Temporal deltas** (weight, BP, labs): expose **both endpoints**, **dates**, and **computed change** columns.
   - **`diagnoses`**: `diagnosis_name`, `diagnosis_date`, `icd10_code` (or codes present in schema).
   - **`prescriptions`**: `medication`, `dosage`, `start_date`, `indication`, `prescribing_doctor` when relevant to the filter.
   - **`procedures`**: `procedure_name`, `procedure_date`, `procedure_code`, `performing_clinician` when that table is used.
   - **`clinical_notes`**: `note_text` (or a truncated/cast snippet if long), `note_id`, date fields used in the query.
   - **`imaging_results`**: `imaging_type`, `body_site`, `findings`, `imaging_date`, `imaging_id`.
   - **`visits`**: `visit_id`, `visit_date`, `hospital`, `visit_type`, `department` when those columns participate in **WHERE** or explain the row.
   - **`social_history`**: `tobacco_use`, `alcohol_use`, etc., when the cohort depends on them.
   - **`patients`**: add **`date_of_birth`**, **`city`**, **`sex`** (or whatever demographic columns exist) when helpful for reading list-style answers—**without** changing who is selected.
3. Add **`JOIN`s** to fact tables **only if** needed for filters already implied—do not widen or narrow the cohort incorrectly. If the SQL uses **`WITH`** / subqueries that already compute weights or dates, **lift those expressions into the outer SELECT** as readable aliases instead of hiding them.
4. Prefer **`ORDER BY`** the main clinical date descending when listing labs/vitals.
5. If the SQL is only **`SELECT COUNT(...)`** and the user asked **how many**, return it **unchanged**.
6. **Do not enrich cohort-level time aggregates:** If the query is already **`DATE_TRUNC(...)` + `AVG`/`SUM`** over **`vitals`**/**`lab_results`** with **no patient identifiers** (population trend / monthly averages), return it **unchanged**—do not add **`patients`** or extra columns that break one-row-per-period grain.

### Output
Reply with **only** one markdown fenced SQL block: ```sql ... ```
