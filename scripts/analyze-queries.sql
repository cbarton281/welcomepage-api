-- ============================================================================
-- Database Query Analysis and Index Creation Script
-- ============================================================================
-- This script contains EXPLAIN ANALYZE statements for all major queries
-- and CREATE INDEX statements for missing indexes.
--
-- Usage:
--   1. Run EXPLAIN ANALYZE statements to see current performance
--   2. Review the execution plans
--   3. Create recommended indexes
--   4. Re-run EXPLAIN ANALYZE to verify improvements
-- ============================================================================

-- ============================================================================
-- SECTION 1: EXPLAIN ANALYZE STATEMENTS
-- ============================================================================
-- Run these to see current query performance
-- Replace placeholder values with actual test data from your database

-- 1. User Lookup by public_id (should be fast - index exists)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE public_id = 'REPLACE_WITH_ACTUAL_PUBLIC_ID';

-- 2. User Lookup by auth_email (likely table scan - needs index)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE auth_email = 'REPLACE_WITH_ACTUAL_EMAIL';

-- 3. User Lookup by share_uuid (should be fast - index exists)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE share_uuid = 'REPLACE_WITH_ACTUAL_SHARE_UUID';

-- 4. Team Lookup by public_id (should be fast - index exists)
EXPLAIN ANALYZE
SELECT * FROM teams WHERE public_id = 'REPLACE_WITH_ACTUAL_TEAM_PUBLIC_ID';

-- 5. Users by Team ID - Published count (likely table scan - needs index)
EXPLAIN ANALYZE
SELECT COUNT(*) FROM welcomepage_users 
WHERE team_id = REPLACE_WITH_ACTUAL_TEAM_ID AND is_draft = false;

-- 6. Users by Team ID - All members (likely table scan - needs index)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = REPLACE_WITH_ACTUAL_TEAM_ID;

-- 7. Team Members with Auth Filters (likely table scan - needs composite index)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = REPLACE_WITH_ACTUAL_TEAM_ID 
  AND auth_email IS NOT NULL 
  AND auth_email != '' 
  AND auth_role IN ('USER', 'ADMIN');

-- 8. Team Members with Full-Text Search (verify GIN index exists)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = REPLACE_WITH_ACTUAL_TEAM_ID 
  AND auth_email IS NOT NULL 
  AND auth_email != '' 
  AND auth_role IN ('USER', 'ADMIN')
  AND search_vector @@ to_tsquery('english', 'REPLACE_WITH_SEARCH_TERM:*');

-- 9. Shared Pages by Team (likely table scan - needs composite index)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users 
WHERE team_id = REPLACE_WITH_ACTUAL_TEAM_ID 
  AND is_shareable = true 
  AND share_uuid IS NOT NULL;

-- 10. Page Visits by visited_user_id (likely table scan - needs index)
EXPLAIN ANALYZE
SELECT * FROM page_visits WHERE visited_user_id = REPLACE_WITH_ACTUAL_USER_ID;

-- 11. Unique Visitor Count (likely table scan - needs composite index)
EXPLAIN ANALYZE
SELECT visited_user_id, COUNT(DISTINCT visitor_public_id) as unique_visits
FROM page_visits 
WHERE visited_user_id IN (REPLACE_WITH_ACTUAL_USER_IDS)
GROUP BY visited_user_id;

-- 12. Verification Code Lookup (should use email index, but composite might be better)
EXPLAIN ANALYZE
SELECT * FROM verification_codes 
WHERE email = 'REPLACE_WITH_ACTUAL_EMAIL' 
  AND code = 'REPLACE_WITH_ACTUAL_CODE' 
  AND used = false;

-- 13. User by slack_user_id (likely table scan - needs index)
EXPLAIN ANALYZE
SELECT * FROM welcomepage_users WHERE slack_user_id = 'REPLACE_WITH_ACTUAL_SLACK_USER_ID';

-- 14. Team by Stripe Customer ID (should be fast - index exists)
EXPLAIN ANALYZE
SELECT * FROM teams WHERE stripe_customer_id = 'REPLACE_WITH_ACTUAL_CUSTOMER_ID';

-- 15. Teams with Sharing Settings (likely table scan - consider GIN index)
EXPLAIN ANALYZE
SELECT * FROM teams WHERE sharing_settings IS NOT NULL;

-- ============================================================================
-- SECTION 2: INDEX CREATION STATEMENTS
-- ============================================================================
-- Create these indexes to improve query performance
-- Run ANALYZE after creating indexes to update statistics

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

-- ============================================================================
-- SECTION 3: UPDATE STATISTICS
-- ============================================================================
-- Run these after creating indexes to update query planner statistics

ANALYZE welcomepage_users;
ANALYZE teams;
ANALYZE page_visits;
ANALYZE verification_codes;

-- ============================================================================
-- SECTION 4: INDEX USAGE MONITORING
-- ============================================================================
-- Run these to monitor index usage

-- Check index usage statistics
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as "Times Used",
    idx_tup_read as "Tuples Read",
    idx_tup_fetch as "Tuples Fetched"
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;

-- Find indexes that are never used (candidates for removal)
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan as "Times Used"
FROM pg_stat_user_indexes
WHERE schemaname = 'public' 
  AND idx_scan = 0
  AND indexname NOT LIKE 'pg_%'
ORDER BY tablename, indexname;

-- Check table sizes and index sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS "Total Size",
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS "Table Size",
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS "Index Size"
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- ============================================================================
-- SECTION 5: VERIFY INDEXES EXIST
-- ============================================================================
-- Run this to see all indexes on your tables

SELECT 
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('welcomepage_users', 'teams', 'page_visits', 'verification_codes', 
                    'slack_state_store', 'slack_pending_installs')
ORDER BY tablename, indexname;

