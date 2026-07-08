from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from overwatch.config import settings
from overwatch.db.engine import sqlalchemy_url
from overwatch.db.models import Base

config = context.config
if config.config_file_name is not None:
    # Keep app loggers alive when migrations run in-process (tests, fixtures):
    # the default disable_existing_loggers=True silently kills them.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sqlalchemy_url(settings.database_url),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(sqlalchemy_url(settings.database_url), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
