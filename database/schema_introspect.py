from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, Connection

SKIP_TABLE_PREFIXES = ("pg_",)
SKIP_TABLE_NAMES = frozenset({"alembic_version", "spatial_ref_sys"})

_LONG_TEXT_NAMES = frozenset(
    {
        "note_text",
        "findings",
        "impression",
        "report_text",
        "raw_text",
        "description",
    }
)

_RANKED_VOCAB: frozenset[tuple[str, str]] = frozenset(
    {
        ("diagnoses", "diagnosis_name"),
        ("diagnoses", "icd10_code"),
        ("lab_results", "test_name"),
        ("diagnosis_codes", "name"),
        ("diagnosis_codes", "code"),
        ("prescriptions", "medication"),
        ("social_history", "tobacco_use"),
        ("social_history", "alcohol_use"),
        ("visits", "visit_type"),
        ("visits", "department"),
        ("clinical_notes", "note_type"),
    }
)


def _safe_sql_ident(name: str) -> bool:
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _is_id_column(name: str, type_str: str) -> bool:
    t = type_str.lower()
    if name.lower() in ("id",):
        return True
    if "int" in t and name.endswith("_id"):
        return True
    return False


def _classify_column_for_sampling(
    col_name: str, type_str: str
) -> Tuple[str, Optional[int]]:
    t = type_str.lower()
    name_l = col_name.lower()

    if not _safe_sql_ident(col_name):
        return "skip", None

    if name_l in _LONG_TEXT_NAMES or ("text" in t and "varchar" not in t):
        return "skip", None

    if "bool" in t:
        return "distinct_text", None

    if "varchar" in t:
        m = re.search(r"varchar\((\d+)\)", t, re.I)
        if m and int(m.group(1)) >= 500:
            return "skip", None

    if any(x in t for x in ("varchar", "char")):
        if name_l in _LONG_TEXT_NAMES:
            return "skip", None
        return "distinct_text", None

    if "text" in t and "varchar" not in t:
        return "skip", None

    if any(x in t for x in ("timestamp", "date")) and not _is_id_column(col_name, type_str):
        return "date_range", None

    if any(
        x in t
        for x in (
            "numeric",
            "float",
            "double",
            "real",
            "decimal",
        )
    ):
        return "numeric_range", None

    if "int" in t and "serial" not in t:
        if _is_id_column(col_name, type_str):
            return "skip", None
        return "numeric_range", None

    return "skip", None


def _format_cell(v: object, max_len: int) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:max_len]
    if isinstance(v, Decimal):
        s = format(v, "f")
        return s[:max_len]
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        s = repr(v)
        return s[:max_len]
    s = str(v).strip()
    if len(s) > max_len:
        return s[: max_len - 1] + "…"
    return s


def _fetch_row_count(conn: Connection, schema: str, table: str) -> Optional[int]:
    if not _safe_sql_ident(schema) or not _safe_sql_ident(table):
        return None
    try:
        q = text(
            f"SELECT COUNT(*) FROM {_quote_ident(schema)}.{_quote_ident(table)}"
        )
        return int(conn.execute(q).scalar_one())
    except Exception:
        return None


def _fetch_ranked_vocab(
    conn: Connection,
    schema: str,
    table: str,
    col: str,
    limit: int,
    max_len: int,
) -> List[str]:
    if not all(_safe_sql_ident(x) for x in (schema, table, col)):
        return []
    try:
        q = text(
            f"SELECT {_quote_ident(col)} AS v, COUNT(*) AS n "
            f"FROM {_quote_ident(schema)}.{_quote_ident(table)} "
            f"WHERE {_quote_ident(col)} IS NOT NULL "
            f"GROUP BY {_quote_ident(col)} "
            f"ORDER BY n DESC, v ASC "
            f"LIMIT :lim"
        )
        rows = conn.execute(q, {"lim": limit}).fetchall()
        out: List[str] = []
        for v, n in rows:
            cell = _format_cell(v, max_len)
            out.append(f"`{cell}` ×{int(n)}")
        return out
    except Exception:
        return []


def _fetch_distinct_sample(
    conn: Connection,
    schema: str,
    table: str,
    col: str,
    limit: int,
    max_len: int,
) -> List[str]:
    if not all(_safe_sql_ident(x) for x in (schema, table, col)):
        return []
    try:
        q = text(
            f"SELECT DISTINCT {_quote_ident(col)} AS v "
            f"FROM {_quote_ident(schema)}.{_quote_ident(table)} "
            f"WHERE {_quote_ident(col)} IS NOT NULL "
            f"LIMIT :lim"
        )
        rows = conn.execute(q, {"lim": limit}).fetchall()
        out: List[str] = []
        for (v,) in rows:
            out.append(_format_cell(v, max_len))
        return sorted(set(out), key=lambda x: (x.lower(), x))[:limit]
    except Exception:
        return []


def _fetch_min_max(
    conn: Connection,
    schema: str,
    table: str,
    col: str,
) -> Optional[Tuple[str, str]]:
    if not all(_safe_sql_ident(x) for x in (schema, table, col)):
        return None
    try:
        q = text(
            f"SELECT MIN({_quote_ident(col)}), MAX({_quote_ident(col)}) "
            f"FROM {_quote_ident(schema)}.{_quote_ident(table)} "
            f"WHERE {_quote_ident(col)} IS NOT NULL"
        )
        row = conn.execute(q).fetchone()
        if not row or row[0] is None:
            return None
        return (
            _format_cell(row[0], 48),
            _format_cell(row[1], 48),
        )
    except Exception:
        return None


def introspect_schema_markdown(
    engine: Engine,
    schema: str = "public",
    max_chars: Optional[int] = 120_000,
    *,
    include_value_samples: bool = True,
    max_distinct_per_column: int = 15,
    max_ranked_vocab: int = 80,
    max_value_chars: int = 72,
) -> str:
    try:
        insp = inspect(engine)
        names = [
            t
            for t in insp.get_table_names(schema=schema)
            if t not in SKIP_TABLE_NAMES
            and not t.startswith(SKIP_TABLE_PREFIXES)
        ]
        names.sort()

        lines: List[str] = []
        total_cols = 0
        distinct_types: set[str] = set()
        fk_lines: List[str] = []

        with engine.connect() as conn:
            for table in names:
                cols = insp.get_columns(table, schema=schema)
                total_cols += len(cols)
                pk_cols = set()
                try:
                    pk = insp.get_pk_constraint(table, schema=schema) or {}
                    pk_cols = set(pk.get("constrained_columns") or [])
                except Exception:
                    pass

                n_rows = (
                    _fetch_row_count(conn, schema, table)
                    if include_value_samples
                    else None
                )
                row_hint = f" — **~{n_rows} rows** in database" if n_rows is not None else ""

                col_parts = []
                for c in cols:
                    name = c["name"]
                    typ = str(c["type"])
                    distinct_types.add(typ)
                    nullable = c.get("nullable", True)
                    null_s = "NULL" if nullable else "NOT NULL"
                    pk_s = " **PK**" if name in pk_cols else ""
                    col_parts.append(f"  - `{name}` — `{typ}`{pk_s}, {null_s}")

                table_lines = [
                    f"#### Table `{table}` ({len(cols)} columns){row_hint}\n"
                    + "\n".join(col_parts)
                ]

                if include_value_samples:
                    samples_block: List[str] = []
                    for c in cols:
                        cn = c["name"]
                        ct = str(c["type"])
                        mode, _ = _classify_column_for_sampling(cn, ct)
                        if mode == "distinct_text":
                            if (table, cn) in _RANKED_VOCAB:
                                ranked = _fetch_ranked_vocab(
                                    conn,
                                    schema,
                                    table,
                                    cn,
                                    max_ranked_vocab,
                                    max_value_chars,
                                )
                                if ranked:
                                    shown = ", ".join(ranked)
                                    tail = ""
                                    if len(ranked) >= max_ranked_vocab:
                                        tail = (
                                            f" *(top {max_ranked_vocab} by frequency; "
                                            f"there may be more labels)*"
                                        )
                                    samples_block.append(
                                        f"  - `{cn}` *(ranked by # rows in this DB)*: "
                                        f"{shown}{tail}"
                                    )
                                continue
                            vals = _fetch_distinct_sample(
                                conn,
                                schema,
                                table,
                                cn,
                                max_distinct_per_column,
                                max_value_chars,
                            )
                            if vals:
                                shown = ", ".join(f"`{v}`" for v in vals)
                                extra = ""
                                if len(vals) >= max_distinct_per_column:
                                    extra = " *(may include additional values in DB)*"
                                samples_block.append(
                                    f"  - `{cn}`: {shown}{extra}"
                                )
                        elif mode == "numeric_range":
                            mm = _fetch_min_max(conn, schema, table, cn)
                            if mm:
                                lo, hi = mm
                                samples_block.append(
                                    f"  - `{cn}`: observed range **`{lo}`** … **`{hi}`**"
                                )
                        elif mode == "date_range":
                            mm = _fetch_min_max(conn, schema, table, cn)
                            if mm:
                                lo, hi = mm
                                samples_block.append(
                                    f"  - `{cn}`: observed span **`{lo}`** … **`{hi}`**"
                                )

                    if samples_block:
                        table_lines.append(
                            "  **Live value profile** (sampled from this database — use to match user phrases):\n"
                            + "\n".join(samples_block)
                        )

                lines.append("\n".join(table_lines))

                try:
                    for fk in insp.get_foreign_keys(table, schema=schema):
                        cc = fk.get("constrained_columns") or []
                        rt = fk.get("referred_table")
                        rc = fk.get("referred_columns") or []
                        if cc and rt and rc:
                            fk_lines.append(
                                f"- `{table}({', '.join(cc)})` → `{rt}({', '.join(rc)})`"
                            )
                except Exception:
                    pass

        hdr = (
            f"**Schema `{schema}` summary:** {len(names)} tables, **{total_cols}** columns, "
            f"**{len(distinct_types)}** distinct SQL column types "
            f"(identifiers use **snake_case** as in the database).\n\n"
        )
        if include_value_samples:
            hdr += (
                "**Data-aware preview:** Includes **row counts**, **numeric/date ranges**, and "
                "for key clinical fields (**diagnosis_name**, **test_name**, meds, etc.) "
                "**ranked observed strings** (how often each label appears). "
                "Build predicates from these **actual** labels first; do not assume absent synonyms exist.\n\n"
            )

        fk_block = ""
        if fk_lines:
            fk_block = (
                "\n\n### Foreign keys (use for JOIN paths)\n"
                + "\n".join(fk_lines[:200])
            )
            if len(fk_lines) > 200:
                fk_block += f"\n… *({len(fk_lines) - 200} more FK constraints omitted)*"

        body = hdr + "\n\n".join(lines) + fk_block

        if max_chars and len(body) > max_chars:
            body = (
                body[: max_chars - 120]
                + "\n\n… *[Schema + value preview truncated for length; FKs and tables above remain authoritative.]*"
            )

        return body
    except Exception as e:
        return (
            "**Schema introspection failed.** "
            f"Reason: `{str(e)[:300]}`. "
            "Derive table and column names only from user context or prior turns."
        )


def compact_clinical_vocab_markdown(
    engine: Engine,
    schema: str = "public",
    *,
    max_ranked_per_col: int = 60,
    max_chars: int = 10_000,
) -> str:
    lines: List[str] = [
        "### Dynamic vocabulary (live database — ranked by row counts)",
        "",
        "Use this to judge whether SQL predicates align with the user’s clinical intent "
        "(labs vs diagnoses vs meds), for **any** use case—not only one condition pair.",
        "",
    ]
    try:
        with engine.connect() as conn:
            sections = [
                ("lab_results", "test_name", "Laboratory tests observed"),
                ("diagnoses", "diagnosis_name", "Diagnosis labels observed"),
                ("prescriptions", "medication", "Medications observed"),
            ]
            for table, col, title in sections:
                ranked = _fetch_ranked_vocab(
                    conn, schema, table, col, max_ranked_per_col, 80
                )
                if ranked:
                    lines.append(f"#### {title} (`{table}.{col}`)")
                    lines.append(", ".join(ranked))
                    lines.append("")
        body = "\n".join(lines).strip()
        if len(body) < 120:
            return "_No ranked clinical vocabulary returned (empty tables or introspection issue)._"
        if max_chars and len(body) > max_chars:
            body = (
                body[: max_chars - 80]
                + "\n\n… *[Vocabulary snapshot truncated; counts still reflect your DB.]*"
            )
        return body
    except Exception as e:
        return f"_Vocabulary snapshot failed: `{str(e)[:200]}`._"


def schema_stats(engine: Engine, schema: str = "public") -> tuple[int, int]:
    try:
        insp = inspect(engine)
        names = [
            t
            for t in insp.get_table_names(schema=schema)
            if t not in SKIP_TABLE_NAMES
            and not t.startswith(SKIP_TABLE_PREFIXES)
        ]
        ncols = 0
        for t in names:
            ncols += len(insp.get_columns(t, schema=schema))
        return len(names), ncols
    except Exception:
        return 0, 0
