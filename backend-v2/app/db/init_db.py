"""Database initialisation.

Alembic is the single source of truth for the schema. Running this module applies all
migrations, so there is never a second, conflicting ``create_all`` path in the app:

    python -m app.db.init_db
"""

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.migrate import upgrade_to_head

log = get_logger("db")


def init_db(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    upgrade_to_head(url)
    log.info("Database schema is at Alembic head.")


if __name__ == "__main__":  # pragma: no cover
    configure_logging(get_settings().log_level)
    init_db()
    print("Database is up to date (alembic head).")
