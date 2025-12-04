# Schema Migration Safety Guide

## Overview
This document outlines the migration from a separate `welcomepage` database to a `welcomepage` schema within the `postgres` database, and the safety considerations for running these migrations in production.

## Changes Made

### 1. New Initial Migration (`20250101_initial_schema_setup.py`)
- **Purpose**: Creates the `welcomepage` schema and sets up the `welcomepagerole` with permissions
- **Safety**: ✅ **SAFE** - Uses `IF NOT EXISTS` checks and idempotent operations
- **Operations**:
  - Creates schema (if not exists)
  - Creates role (if not exists)
  - Grants permissions (idempotent)
  - Sets default privileges

### 2. Updated Existing Migrations
- Updated `507ccf8e06d8` to reference the new initial migration
- Updated table creation to use `welcomepage` schema
- All subsequent migrations will automatically use the schema via search_path

### 3. Updated Configuration Files
- `alembic/env.py`: Configured to use `welcomepage` schema
- `alembic.ini`: Changed default database from `welcomepage` to `postgres`
- `database.py`: Added schema search_path to connection

### 4. Updated Models
- All models now specify `__table_args__ = {'schema': 'welcomepage'}`
- This ensures SQLAlchemy queries use the correct schema

## Production Safety Assessment

### ✅ SAFE Operations (No Data Risk)
1. **Schema Creation**: `CREATE SCHEMA IF NOT EXISTS welcomepage`
   - Will not affect existing data
   - Idempotent - safe to run multiple times

2. **Role Creation**: `CREATE ROLE IF NOT EXISTS welcomepagerole`
   - Will not affect existing data
   - Idempotent - safe to run multiple times

3. **Permission Grants**: All GRANT statements
   - Idempotent operations
   - Will not modify or delete data
   - Safe to run multiple times

### ⚠️ IMPORTANT Considerations

#### 1. Existing Data Location
**CRITICAL QUESTION**: Where is your production data currently located?

- **Scenario A**: Data is in a separate `welcomepage` database
  - ✅ **SAFE**: The migration scripts won't touch that database
  - You'll need to manually migrate data later (separate process)
  
- **Scenario B**: Data is already in `postgres` database, `public` schema
  - ⚠️ **REQUIRES ATTENTION**: Tables won't be automatically moved
  - You'll need a data migration script to move tables from `public` to `welcomepage` schema
  - **DO NOT RUN** the new migrations until you've handled existing data

#### 2. Connection String Changes
- Your application's `DATABASE_URL` must point to the `postgres` database (not `welcomepage`)
- The schema is handled via search_path in `database.py`
- **Action Required**: Update production `DATABASE_URL` environment variable

#### 3. Role Password
- The migration creates the role but **DOES NOT** set the password
- You must set the password separately:
  ```sql
  ALTER ROLE welcomepagerole WITH PASSWORD 'your-secure-password';
  ```
- Update your connection strings to use this password

#### 4. Application Restart Required
- After running migrations, you **MUST** restart your application
- The application needs to reconnect with the new schema configuration

## Pre-Migration Checklist

Before running migrations in production:

- [ ] **Backup your database** (CRITICAL - always backup before migrations)
- [ ] Verify current data location (which database/schema?)
- [ ] Test migrations on a staging/dev environment first
- [ ] Update `DATABASE_URL` to point to `postgres` database
- [ ] Set the `welcomepagerole` password
- [ ] Verify you can connect to `postgres` database with appropriate permissions
- [ ] Plan for application downtime during migration (if needed)

## Running the Migration

### Step 1: Verify Current State
```sql
-- Check if schema already exists
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'welcomepage';

-- Check if role already exists
SELECT rolname FROM pg_roles WHERE rolname = 'welcomepagerole';

-- Check current database
SELECT current_database();
```

### Step 2: Run Migration
```bash
# From the db-migrations directory
alembic upgrade head
```

### Step 3: Set Role Password (if role was just created)
```sql
ALTER ROLE welcomepagerole WITH PASSWORD 'your-secure-password';
```

### Step 4: Verify Migration
```sql
-- Check schema exists
SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'welcomepage';

-- Check tables in schema
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'welcomepage';

-- Check alembic version
SELECT * FROM welcomepage.alembic_version;
```

## Rollback Plan

If something goes wrong:

1. **The downgrade function** will revoke permissions but **WILL NOT** drop the schema or data
2. To completely rollback:
   ```sql
   -- Revoke permissions (handled by downgrade)
   -- Then manually if needed:
   DROP SCHEMA IF EXISTS welcomepage CASCADE;
   DROP ROLE IF EXISTS welcomepagerole;
   ```
3. **Restore from backup** if data was affected

## Data Migration (If Needed)

If you have existing tables in the `public` schema that need to be moved:

```sql
-- Example: Move teams table
ALTER TABLE public.teams SET SCHEMA welcomepage;

-- Example: Move welcomepage_users table
ALTER TABLE public.welcomepage_users SET SCHEMA welcomepage;

-- Repeat for all tables
```

**WARNING**: This is a **DATA MODIFICATION** operation. Test thoroughly first!

## Post-Migration Verification

After migration:

1. ✅ Verify schema exists: `SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'welcomepage';`
2. ✅ Verify tables exist: `SELECT table_name FROM information_schema.tables WHERE table_schema = 'welcomepage';`
3. ✅ Verify role has permissions: `\dp welcomepage.*` (in psql)
4. ✅ Test application connectivity
5. ✅ Verify application queries work correctly
6. ✅ Monitor application logs for any schema-related errors

## Risk Summary

| Operation | Risk Level | Data Impact | Reversible |
|-----------|-----------|-------------|------------|
| Create schema | ✅ Low | None | Yes |
| Create role | ✅ Low | None | Yes |
| Grant permissions | ✅ Low | None | Yes |
| Update connection strings | ⚠️ Medium | None (if done correctly) | Yes |
| Move existing tables | 🔴 High | Data movement | Yes (with backup) |

## Support

If you encounter issues:
1. Check Alembic migration logs
2. Verify database connection settings
3. Check application logs for schema-related errors
4. Restore from backup if necessary

## Notes

- The migration is designed to be **idempotent** - safe to run multiple times
- No data will be deleted by these migrations
- The schema creation and role setup are **completely safe** for production
- The main risk is in **connection configuration** and **existing data location**

