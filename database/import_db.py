import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine

from database.models import Base
import config

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "synclin_database_snapshot.sql"

DB_URL = config.DATABASE_URL


def import_db():
    if not FIXTURE_PATH.exists():
        raise SystemExit(
            f"Fixture not found at {FIXTURE_PATH}.\n"
            "Run `python -m database.build_fixture` once to generate it."
        )

    engine = create_engine(DB_URL)

    print(f"Dropping and recreating schema on {DB_URL} ...")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    sql = FIXTURE_PATH.read_text()
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)

    print(f"Imported static SynClin-SQL fixture ({FIXTURE_PATH.name}) into {DB_URL}")


if __name__ == "__main__":
    import_db()
