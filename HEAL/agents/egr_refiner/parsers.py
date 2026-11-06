import re


def extract_sql(text: str) -> str:
    sql_match = re.search(r"```sql(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if sql_match:
        return sql_match.group(1).strip().replace(";", "")
    return text.strip().replace(";", "")
