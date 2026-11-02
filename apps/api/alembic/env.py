"""Alembic environment for the auth tables.

The URL is read from ``SYNAPSE_DATABASE_URL`` (falling back to the same SQLite
default the API uses) or from ``-x``/``sqlalchemy.url``; nothing is checked in.
Both dialects the compose contract promises are supported:

* SQLite: ``sqlite+pysqlite:///var/auth.sqlite3`` with ``render_as_batch`` so a
  future column change can still be expressed as a table rebuild.
* PostgreSQL: ``postgresql+psycopg://user:pass@host:5432/db``.

Offline mode (``alembic upgrade head --sql``) compiles DDL without connecting,
which is how the test suite proves the PostgreSQL dialect accepts the migration
without needing a server.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from synapse.infrastructure.auth.db import (  # noqa: E402
    Base,
    create_auth_engine,
    normalize_database_url,
)
from synapse.infrastructure.auth.settings import DEFAULT_DATABASE_URL  # noqa: E402
from synapse.infrastructure.credentials.db import (  # noqa: E402, F401
    UserModelCredentialRow,
)

config = context.config

if config.config_file_name is not None:
    # ``disable_existing_loggers=False`` because pytest and the API configure
    # their own loggers; a migration must not silence them.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    configured = (config.get_main_option("sqlalchemy.url") or "").strip()
    if configured:
        return normalize_database_url(configured)
    return normalize_database_url(
        os.getenv("SYNAPSE_DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_auth_engine(_database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()