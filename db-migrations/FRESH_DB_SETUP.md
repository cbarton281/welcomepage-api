# Fresh Database Setup Guide

## Quick Start

For a **completely fresh** postgres database, simply run:

```bash
cd db-migrations
alembic upgrade head
```

**For Supabase production**, use your typical command format but with `db-name=postgres`:

```bash
alembic -x db-host=db.xastkogrfeblbsvmbkew.supabase.co \
  -x db-port=5432 \
  -x db-name=postgres \
  -x db-owner=postgres \
  -x db-owner-password=XXX \
  upgrade head
```

**IMPORTANT**: Change `db-name=welcomepage` to `db-name=postgres`. The `welcomepage` is now a **schema** within the `postgres` database, not a separate database.

This will run all migrations in order, starting from the initial schema setup.

## Step-by-Step Instructions

### 1. Navigate to migrations directory
```bash
cd db-migrations
```

### 2. Verify your database connection

The default connection in `alembic.ini` is:
```
postgresql://postgres:wpdev@localhost/postgres
```

**If your connection details differ**, you can override them using `-x` arguments:

```bash
alembic upgrade head \
  -x db-host=your-host \
  -x db-port=5432 \
  -x db-name=postgres \
  -x db-owner=postgres \
  -x db-owner-password=your-password
```

**For Supabase or remote databases**, use:
```bash
alembic upgrade head \
  -x db-host=db.xastkogrfeblbsvmbkew.supabase.co \
  -x db-port=5432 \
  -x db-name=postgres \
  -x db-owner=postgres \
  -x db-owner-password=your-password
```

**IMPORTANT**: Note that `db-name=postgres` (not `welcomepage`). The `welcomepage` is now a **schema** within the `postgres` database, not a separate database.

### 3. Check current migration status (optional)
```bash
alembic current
```

On a fresh database, this should show nothing (no migrations applied yet).

### 4. Run all migrations
```bash
alembic upgrade head
```

This will:
1. Create the `welcomepage` schema
2. Create the `welcomepagerole` (without password - set separately)
3. Set up permissions
4. Create all tables in the correct order
5. Apply all subsequent migrations

### 5. Verify the migration

Check that everything was created:

```sql
-- Connect to your database, then run:

-- Check schema exists
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'welcomepage';

-- Check tables were created
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'welcomepage'
ORDER BY table_name;

-- Check alembic version (should show latest revision)
SELECT * FROM welcomepage.alembic_version;

-- Check role exists
SELECT rolname FROM pg_roles WHERE rolname = 'welcomepagerole';
```

### 6. Set the role password (IMPORTANT)

The migration creates the role but doesn't set a password. You must do this manually:

```sql
ALTER ROLE welcomepagerole WITH PASSWORD 'your-secure-password';
```

**Note**: Update your application's `DATABASE_URL` to use this password if you're using the `welcomepagerole` user.

## Expected Output

When you run `alembic upgrade head`, you should see output like:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 20250101, Initial schema and role setup
INFO  [alembic.runtime.migration] Running upgrade 20250101 -> 507ccf8e06d8, Initial migration
INFO  [alembic.runtime.migration] Running upgrade 507ccf8e06d8 -> 20250715, create_verification_codes_table
... (continues through all migrations)
INFO  [alembic.runtime.migration] Running upgrade 20250863 -> 20250865, add_team_members_sorting_indexes
```

## Troubleshooting

### Error: "relation already exists"
- The database isn't actually fresh, or a previous migration partially ran
- Check what exists: `SELECT * FROM welcomepage.alembic_version;`
- If needed, manually clean up and start over

### Error: "schema welcomepage does not exist"
- This shouldn't happen if running from scratch, but if it does:
- The initial migration (`20250101`) should create it
- Check that all migration files are present

### Error: Connection refused / Authentication failed
- Verify your connection details
- For Supabase: Check you're using the correct connection string
- Ensure SSL is enabled (Supabase requires it)

### Error: "role welcomepagerole already exists"
- This is fine - the migration uses `IF NOT EXISTS`
- The migration will continue normally

## What Gets Created

After running migrations, you'll have:

1. **Schema**: `welcomepage`
2. **Role**: `welcomepagerole` (password must be set separately)
3. **Tables** (in `welcomepage` schema):
   - `teams`
   - `welcomepage_users`
   - `verification_codes`
   - `slack_state_store`
   - `slack_pending_installs`
   - `page_visits`
   - `alembic_version` (tracks migration state)

4. **Permissions**: `welcomepagerole` has full access to the `welcomepage` schema

## Next Steps

After migrations complete:

1. ✅ Set the `welcomepagerole` password
2. ✅ Update your application's `DATABASE_URL` to point to `postgres` database
3. ✅ Ensure `DATABASE_URL` includes the schema search path (handled by `database.py`)
4. ✅ Test your application connection
5. ✅ Verify queries work correctly

## Rollback (if needed)

If something goes wrong and you need to start over:

```sql
-- WARNING: This will delete ALL data in the welcomepage schema
DROP SCHEMA IF EXISTS welcomepage CASCADE;
DROP ROLE IF EXISTS welcomepagerole;
```

Then run `alembic upgrade head` again.

