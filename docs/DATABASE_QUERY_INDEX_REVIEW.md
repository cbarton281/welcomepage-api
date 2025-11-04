# Database Query Index Review

This document provides a comprehensive review of database queries, identifies potential table scans, and provides EXPLAIN ANALYZE statements for performance analysis.

## Current Indexes (from Models)

### WelcomepageUser (`welcomepage_users`)
- `public_id` - UNIQUE INDEX (exists)
- `share_uuid` - UNIQUE INDEX (exists)
- `search_vector` - tsvector type (should have GIN index for full-text search)

### Team (`teams`)
- `id` - PRIMARY KEY (exists)
- `public_id` - UNIQUE INDEX (exists)
- `stripe_customer_id` - UNIQUE INDEX (exists)
- `stripe_subscription_id` - UNIQUE INDEX (exists)

### VerificationCode (`verification_codes`)
- `email` - INDEX (exists)
- `public_id` - INDEX (exists)

### SlackStateStore (`slack_state_store`)
- `id` - PRIMARY KEY (exists)
- `state` - UNIQUE INDEX (exists)

### SlackPendingInstall (`slack_pending_installs`)
- `id` - PRIMARY KEY (exists)
- `nonce` - UNIQUE INDEX (exists)

## Potentially Missing Indexes

### Critical Missing Indexes

1. **welcomepage_users.team_id** - Foreign key but no explicit index
2. **welcomepage_users.auth_email** - Frequently queried, no index
3. **welcomepage_users.slack_user_id** - Queried in user lookup flows
4. **page_visits.visited_user_id** - Critical for visit statistics
5. **page_visits.visitor_public_id** - Used in visit queries
6. **Composite indexes** for common query patterns

## Representative Queries and EXPLAIN ANALYZE Statements

### 1. User Lookup by public_id

**Query Location:** `api/user.py:922`, `api/user.py:112`, `api/user.py:189`, `api/user.py:224`

**SQL Query:**
```sql
SELECT * FROM welcomepage_users WHERE public_id = 'abc123';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE public_id = 'abc123';
```

**Expected:** Index scan on `public_id` (index exists)

---

### 2. User Lookup by auth_email

**Query Location:** `api/user.py:184`, `api/user.py:209`, `api/verification_code.py:49`, `api/verification_code.py:121`, `api/verification_code.py:155`, `api/verification_code.py:243`

**SQL Query:**
```sql
SELECT * FROM welcomepage_users WHERE auth_email = 'user@example.com';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE auth_email = 'user@example.com';
```

**Expected:** Table scan (index missing) - **NEEDS INDEX**

**Recommended Index:**
```sql
CREATE INDEX idx_welcomepage_users_auth_email ON welcomepage_users(auth_email);
```

---

### 3. User Lookup by share_uuid

**Query Location:** `api/user.py` (share page access)

**SQL Query:**
```sql
SELECT * FROM welcomepage_users WHERE share_uuid = 'xyz789';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE share_uuid = 'xyz789';
```

**Expected:** Index scan on `share_uuid` (index exists)

---

### 4. Team Lookup by public_id

**Query Location:** Multiple endpoints (`api/team.py:59`, `api/user.py:1025`, etc.)

**SQL Query:**
```sql
SELECT * FROM teams WHERE public_id = 'team123';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM teams WHERE public_id = 'team123';
```

**Expected:** Index scan on `public_id` (index exists)

---

### 5. Users by Team ID (with filters)

**Query Location:** `api/team.py:76-79`, `api/team.py:1033`, `api/user.py:1033`

**SQL Query:**
```sql
-- Published count
SELECT COUNT(*) FROM welcomepage_users 
WHERE team_id = 42 AND is_draft = false;

-- Team members
SELECT * FROM welcomepage_users 
WHERE team_id = 42;
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT COUNT(*) FROM welcomepage_users 
WHERE team_id = 42 AND is_draft = false;

EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = 42;
```

**Expected:** Table scan (index missing) - **NEEDS INDEX**

**Recommended Index:**
```sql
CREATE INDEX idx_welcomepage_users_team_id ON welcomepage_users(team_id);
-- Composite index for common query pattern
CREATE INDEX idx_welcomepage_users_team_draft ON welcomepage_users(team_id, is_draft);
```

---

### 6. Team Members with Auth Filters

**Query Location:** `api/team.py:128-133`, `api/team.py:283-288`, `api/team.py:721-726`

**SQL Query:**
```sql
SELECT * FROM welcomepage_users 
WHERE team_id = 42 
  AND auth_email IS NOT NULL 
  AND auth_email != '' 
  AND auth_role IN ('USER', 'ADMIN');
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = 42 
  AND auth_email IS NOT NULL 
  AND auth_email != '' 
  AND auth_role IN ('USER', 'ADMIN');
```

**Expected:** Table scan (index missing) - **NEEDS COMPOSITE INDEX**

**Recommended Index:**
```sql
CREATE INDEX idx_welcomepage_users_team_auth ON welcomepage_users(team_id, auth_role) 
WHERE auth_email IS NOT NULL AND auth_email != '';
```

---

### 7. Team Members with Search (Full-Text)

**Query Location:** `api/team.py:295-321`, `api/team.py:1296-1315`

**SQL Query:**
```sql
SELECT * FROM welcomepage_users 
WHERE team_id = 42 
  AND auth_email IS NOT NULL 
  AND auth_email != '' 
  AND auth_role IN ('USER', 'ADMIN')
  AND search_vector @@ to_tsquery('english', 'toronto:*');
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = 42 
  AND auth_email IS NOT NULL 
  AND auth_email != '' 
  AND auth_role IN ('USER', 'ADMIN')
  AND search_vector @@ to_tsquery('english', 'toronto:*');
```

**Expected:** Should use GIN index on search_vector - **VERIFY GIN INDEX EXISTS**

**Recommended Index (if missing):**
```sql
CREATE INDEX idx_welcomepage_users_search_vector ON welcomepage_users USING GIN(search_vector);
```

---

### 8. Shared Pages by Team

**Query Location:** `api/team.py:1289-1293`

**SQL Query:**
```sql
SELECT * FROM welcomepage_users 
WHERE team_id = 42 
  AND is_shareable = true 
  AND share_uuid IS NOT NULL;
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = 42 
  AND is_shareable = true 
  AND share_uuid IS NOT NULL;
```

**Expected:** Table scan (index missing) - **NEEDS COMPOSITE INDEX**

**Recommended Index:**
```sql
CREATE INDEX idx_welcomepage_users_team_shareable ON welcomepage_users(team_id, is_shareable, share_uuid) 
WHERE is_shareable = true AND share_uuid IS NOT NULL;
```

---

### 9. Page Visits by visited_user_id

**Query Location:** `api/visits.py:271`, `api/team.py:179-184`

**SQL Query:**
```sql
-- Visit stats
SELECT * FROM page_visits WHERE visited_user_id = 123;

-- Unique visitor count
SELECT visited_user_id, COUNT(DISTINCT visitor_public_id) as unique_visits
FROM page_visits 
WHERE visited_user_id IN (123, 456, 789)
GROUP BY visited_user_id;
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM page_visits WHERE visited_user_id = 123;

EXPLAIN ANALYZE
SELECT visited_user_id, COUNT(DISTINCT visitor_public_id) as unique_visits
FROM page_visits 
WHERE visited_user_id IN (123, 456, 789)
GROUP BY visited_user_id;
```

**Expected:** Table scan (index missing) - **NEEDS INDEX**

**Recommended Indexes:**
```sql
CREATE INDEX idx_page_visits_visited_user_id ON page_visits(visited_user_id);
CREATE INDEX idx_page_visits_visitor_public_id ON page_visits(visitor_public_id);
-- Composite for the grouped query
CREATE INDEX idx_page_visits_user_visitor ON page_visits(visited_user_id, visitor_public_id);
```

---

### 10. Verification Code Lookup

**Query Location:** `api/verification_code.py:46`, `api/verification_code.py:215`

**SQL Query:**
```sql
-- Mark existing codes as used
UPDATE verification_codes 
SET used = true 
WHERE email = 'user@example.com' AND used = false;

-- Verify code
SELECT * FROM verification_codes 
WHERE email = 'user@example.com' 
  AND code = '123456' 
  AND used = false;
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
UPDATE verification_codes 
SET used = true 
WHERE email = 'user@example.com' AND used = false;

EXPLAIN ANALYZE
SELECT * FROM verification_codes 
WHERE email = 'user@example.com' 
  AND code = '123456' 
  AND used = false;
```

**Expected:** Should use email index, but composite might be better

**Recommended Index:**
```sql
CREATE INDEX idx_verification_codes_email_used ON verification_codes(email, used) 
WHERE used = false;
```

---

### 11. User by slack_user_id

**Query Location:** `api/user.py` (upsert logic), Slack integration flows

**SQL Query:**
```sql
SELECT * FROM welcomepage_users WHERE slack_user_id = 'U123456';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE slack_user_id = 'U123456';
```

**Expected:** Table scan (index missing) - **NEEDS INDEX**

**Recommended Index:**
```sql
CREATE INDEX idx_welcomepage_users_slack_user_id ON welcomepage_users(slack_user_id) 
WHERE slack_user_id IS NOT NULL;
```

---

### 12. Team by Stripe Customer ID

**Query Location:** Stripe webhook handlers, billing endpoints

**SQL Query:**
```sql
SELECT * FROM teams WHERE stripe_customer_id = 'cus_abc123';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM teams WHERE stripe_customer_id = 'cus_abc123';
```

**Expected:** Index scan on `stripe_customer_id` (index exists)

---

### 13. Slack State Store Lookup

**Query Location:** `api/slack.py` (OAuth callback)

**SQL Query:**
```sql
SELECT * FROM slack_state_store WHERE state = 'uuid-state-value';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM slack_state_store WHERE state = 'uuid-state-value';
```

**Expected:** Index scan on `state` (index exists)

---

### 14. Slack Pending Install Lookup

**Query Location:** `api/slack.py:159`, `api/slack.py:186`

**SQL Query:**
```sql
SELECT * FROM slack_pending_installs WHERE nonce = 'nonce-value';
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM slack_pending_installs WHERE nonce = 'nonce-value';
```

**Expected:** Index scan on `nonce` (index exists)

---

### 15. Team Sharing Settings Lookup (JSONB Query)

**Query Location:** `api/team.py:1262-1267`

**SQL Query:**
```sql
-- This query scans all teams with sharing_settings to find matching UUID
SELECT * FROM teams 
WHERE sharing_settings IS NOT NULL;
-- Then filters in application code by checking sharing_settings->>'uuid'
```

**EXPLAIN ANALYZE:**
```sql
EXPLAIN ANALYZE
SELECT * FROM teams WHERE sharing_settings IS NOT NULL;
```

**Expected:** Table scan - **CONSIDER GIN INDEX**

**Recommended Index:**
```sql
CREATE INDEX idx_teams_sharing_settings_uuid ON teams USING GIN((sharing_settings->>'uuid'));
-- Or for full JSONB indexing
CREATE INDEX idx_teams_sharing_settings ON teams USING GIN(sharing_settings);
```

---

## Complete Index Creation Script

```sql
-- Critical indexes for welcomepage_users
CREATE INDEX IF NOT EXISTS idx_welcomepage_users_auth_email 
  ON welcomepage_users(auth_email);

CREATE INDEX IF NOT EXISTS idx_welcomepage_users_team_id 
  ON welcomepage_users(team_id);

CREATE INDEX IF NOT EXISTS idx_welcomepage_users_slack_user_id 
  ON welcomepage_users(slack_user_id) 
  WHERE slack_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_welcomepage_users_team_draft 
  ON welcomepage_users(team_id, is_draft);

CREATE INDEX IF NOT EXISTS idx_welcomepage_users_team_auth 
  ON welcomepage_users(team_id, auth_role) 
  WHERE auth_email IS NOT NULL AND auth_email != '';

CREATE INDEX IF NOT EXISTS idx_welcomepage_users_team_shareable 
  ON welcomepage_users(team_id, is_shareable, share_uuid) 
  WHERE is_shareable = true AND share_uuid IS NOT NULL;

-- Full-text search index (verify this exists)
CREATE INDEX IF NOT EXISTS idx_welcomepage_users_search_vector 
  ON welcomepage_users USING GIN(search_vector);

-- Critical indexes for page_visits
CREATE INDEX IF NOT EXISTS idx_page_visits_visited_user_id 
  ON page_visits(visited_user_id);

CREATE INDEX IF NOT EXISTS idx_page_visits_visitor_public_id 
  ON page_visits(visitor_public_id);

CREATE INDEX IF NOT EXISTS idx_page_visits_user_visitor 
  ON page_visits(visited_user_id, visitor_public_id);

-- Verification codes composite index
CREATE INDEX IF NOT EXISTS idx_verification_codes_email_used 
  ON verification_codes(email, used) 
  WHERE used = false;

-- Teams JSONB indexes for sharing_settings
CREATE INDEX IF NOT EXISTS idx_teams_sharing_settings 
  ON teams USING GIN(sharing_settings);
```

## Running EXPLAIN ANALYZE in Production

To analyze query performance on your production database:

1. **Connect to your PostgreSQL database:**
```bash
psql $DATABASE_URL
```

2. **For each query above, run the EXPLAIN ANALYZE statement** to see actual execution plans.

3. **Look for these warning signs:**
   - `Seq Scan` (sequential scan) on large tables
   - High `Execution Time` 
   - Large `rows` values in scan operations
   - `Filter` operations that remove many rows

4. **Good signs:**
   - `Index Scan` or `Index Only Scan`
   - Low execution time
   - Small number of rows examined

## Index Maintenance

After creating indexes:

1. **Update statistics:**
```sql
ANALYZE welcomepage_users;
ANALYZE teams;
ANALYZE page_visits;
ANALYZE verification_codes;
```

2. **Monitor index usage:**
```sql
-- Check index usage statistics
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;
```

3. **Check for unused indexes:**
```sql
-- Find indexes that are never used
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan
FROM pg_stat_user_indexes
WHERE schemaname = 'public' 
  AND idx_scan = 0
  AND indexname NOT LIKE 'pg_%'
ORDER BY tablename, indexname;
```

## Summary

**High Priority Indexes to Create:**
1. `welcomepage_users.auth_email` - Used in many authentication flows
2. `welcomepage_users.team_id` - Most common query pattern
3. `page_visits.visited_user_id` - Critical for visit statistics
4. `welcomepage_users.search_vector` GIN index - For full-text search
5. Composite indexes for common query patterns

**Medium Priority:**
1. `welcomepage_users.slack_user_id` - Slack integration
2. `page_visits.visitor_public_id` - Visit analytics
3. Composite indexes for filtered queries

**Low Priority (but still beneficial):**
1. JSONB indexes on teams for sharing_settings queries
2. Partial indexes with WHERE clauses for filtered queries

## Recommended Workflow

1. **Check for missing indexes:**
   ```bash
   python scripts/check_indexes.py
   ```

2. **Generate Alembic migration** (recommended - applies to all environments):
   ```bash
   python scripts/check_indexes.py --generate-migration
   ```
   This creates a migration file in `db-migrations/alembic/versions/` that follows your existing Alembic workflow.

3. **Review the generated migration** before applying:
   ```bash
   # Review the generated migration
   cat db-migrations/alembic/versions/YYYYMMDD_add_missing_performance_indexes.py
   ```

4. **Apply the migration** to your database:
   ```bash
   cd db-migrations
   alembic upgrade head
   ```

5. **(Optional) Run EXPLAIN ANALYZE** to verify performance improvements:
   ```bash
   python scripts/check_indexes.py --explain
   ```

**Note:** Using `--generate-migration` is the recommended approach as it ensures indexes are applied consistently across all environments (dev, staging, production) through Alembic version control, rather than creating indexes directly on the database.

