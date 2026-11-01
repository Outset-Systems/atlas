"""Alembic environment for the Atlas DB backbone.

The URL is the app's own (`store.db_url()`), so deployments run
`alembic upgrade head` with no ini edits.
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from store import db_url
from store.models import Base

config = context.config

# The app's own answer, so a migration lands in the database the app reads.
# `%` is escaped for the config parser a URL passes through.
config.set_main_option("sqlalchemy.url", db_url().replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER support for future revisions
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
