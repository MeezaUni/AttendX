"""Schema management with Alembic (``attendx migrate`` / app start-up)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from attendx.db import Database

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser escaping
    return cfg


def upgrade_or_create(db: Database) -> None:
    """Bring the database to the latest revision (creates every table on a fresh database)."""
    cfg = alembic_config(str(db.engine.url))
    with db.engine.connect() as conn:
        sqlite = conn.dialect.name == "sqlite"
        if sqlite:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        try:
            with conn.begin():
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
                if sqlite and conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("Foreign key check failed after migration")
        finally:
            if sqlite:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                conn.commit()
