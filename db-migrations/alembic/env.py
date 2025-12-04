from logging.config import fileConfig
from alembic import context
import logging
from dotenv import load_dotenv
import os
import sys
from sqlalchemy import create_engine
from sqlalchemy import pool
import sqlalchemy as sa

default_dotenv_path = '../.env'
dotenv_path = default_dotenv_path

default_db_owner: str = "postgres"
default_db_owner_password: str = ""
default_db_host: str = "localhost"
default_db_port: str = "5432"
default_db_name: str = "postgres"

db_owner = default_db_owner
db_owner_password = default_db_owner_password
db_host = default_db_host
db_port = default_db_port
db_name = default_db_name

# Use Alembic's x-arguments
for x_arg in context.get_x_argument(as_dictionary=False):
    print(f"x_arg = [{x_arg}]")
    if x_arg.lower().strip().startswith('db-owner='):
        db_owner = x_arg.split('=', 1)[1].strip()
    elif x_arg.lower().strip().startswith('db-owner-password='):
        db_owner_password = x_arg.split('=', 1)[1].strip()
    elif x_arg.lower().strip().startswith('db-host='):
        db_host = x_arg.split('=', 1)[1].strip()
    elif x_arg.lower().strip().startswith('db-port='):
        db_port = x_arg.split('=', 1)[1].strip()
    elif x_arg.lower().strip().startswith('db-name='):
        db_name = x_arg.split('=', 1)[1].strip()
    elif x_arg.lower().strip().startswith('dotenv-path='):
        dotenv_path = x_arg.split('=', 1)[1].strip()
    else:
        print(f"ERROR: Unrecognized Alembic -x argument: '{x_arg}' Valid arguments are: db-owner, db-owner-password, db-host, db-port, db-name, dotenv-path", file=sys.stderr)
        sys.exit(1)

load_dotenv(dotenv_path=dotenv_path)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

log = logging.getLogger('alembic.env')

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    
    db_url = f"postgresql+psycopg2://{db_owner}:{db_owner_password}@{db_host}:{db_port}/{db_name}"
    print(f"[alembic] offline db_url = [{db_url}]")
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,  # Include non-default schemas in autogenerate
        version_table_schema='welcomepage',  # Store alembic_version table in welcomepage schema
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    db_url = f"postgresql+psycopg2://{db_owner}:{db_owner_password}@{db_host}:{db_port}/{db_name}"
    print(f"[alembic] online db_url = [{db_url}]")
    connectable = create_engine(
        db_url,
        connect_args={"sslmode": "require"},
        poolclass=pool.NullPool
    )

    # connectable = create_engine(db_url, poolclass=pool.NullPool)
    # connectable = engine_from_config(
    #     config.get_section(config.config_ini_section, {}),
    #     prefix="sqlalchemy.",
    #     poolclass=pool.NullPool,
    # )

    # For pgbouncer/connection pooling, ensure proper transaction handling
    # First, check schema with a separate connection to avoid transaction conflicts
    with connectable.connect() as check_conn:
        schema_check = check_conn.execute(sa.text("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.schemata 
                WHERE schema_name = 'welcomepage'
            )
        """)).scalar()
        check_conn.commit()  # Commit the check query
    
    # Only use welcomepage schema for version table if schema already exists
    # Otherwise, use public schema initially (first migration will create welcomepage schema)
    version_table_schema = 'welcomepage' if schema_check else None
    
    log.info(f"Schema check result: {schema_check}, using version_table_schema: {version_table_schema}")
    log.info(f"Connection URL: postgresql://{db_owner}:***@{db_host}:{db_port}/{db_name}")
    
    # Now use a fresh connection for migrations
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,  # Include non-default schemas in autogenerate
            version_table_schema=version_table_schema,  # Use welcomepage if exists, else public
        )

        # Run migrations - use single transaction for all migrations
        # For pgbouncer, we need to ensure the transaction commits properly
        log.info("Starting migrations...")
        try:
            # Use context.begin_transaction() - it should handle commit/rollback
            with context.begin_transaction():
                log.info("Transaction started, running migrations...")
                # Set search path within the transaction
                connection.execute(sa.text("SET LOCAL search_path TO welcomepage, public"))
                context.run_migrations()
                log.info("All migrations executed, transaction should commit...")
            log.info("Migrations completed successfully - transaction committed")
        except Exception as e:
            log.error(f"Migration failed with error: {e}", exc_info=True)
            import traceback
            log.error(f"Full traceback: {traceback.format_exc()}")
            raise


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
