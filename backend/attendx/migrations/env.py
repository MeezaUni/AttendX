"""Alembic environment: URL comes from the caller (attendx.migrate) or ATTENDX settings."""

from alembic import context

from attendx.config import get_settings
from attendx.models import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or get_settings().db_url
target_metadata = Base.metadata


def run_migrations_online() -> None:
    from attendx.db import make_engine

    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
