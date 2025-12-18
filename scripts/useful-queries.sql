select slack_user_id, team_id, auth_email, is_draft, auth_role, * 
from welcomepage.welcomepage_users  
order by created_at desc;

select is_draft, share_uuid, is_shareable, auth_email, auth_role, team_id, * 
from welcomepage.welcomepage_users 
where auth_email like 'charles.barton+34%gmail.com'  
order by auth_email;

select is_draft, share_uuid, is_shareable, auth_email, auth_role, team_id, * 
from welcomepage.welcomepage_users 
where public_id like 'bgs-0%';

--171
select is_draft, share_uuid, is_shareable, auth_email, auth_role, team_id, * 
from welcomepage.welcomepage_users 
where auth_email like 'charles.barton+%@gmail.com'
order by auth_email;

select auth_email, public_id,  * 
from welcomepage.welcomepage_users 
where team_id in (select id from welcomepage.teams where public_id = 'bgs-team01')

select name, auth_email, is_shareable, share_uuid, * 
from welcomepage.welcomepage_users 
where name like 'Angel%';

select search_vector 
from welcomepage.welcomepage_users 
where name like 'jos%';

select auth_email, is_shareable, share_uuid, is_draft, * 
from welcomepage.welcomepage_users 
where team_id IN (select id from welcomepage.teams where public_id = 'ied3vv24li')
  AND is_shareable IS true;

select t.* 
from welcomepage.teams t 
join welcomepage.welcomepage_users w on t.id = w.team_id 
where w.auth_email = 'charles.barton+100@gmail.com';

select * 
from welcomepage.welcomepage_users 
where slack_user_id = 'U09EX7M3S2F';

select count(w.*) 
from welcomepage.welcomepage_users w  
where w.is_draft = false and team_id = 26;

select count(*) 
from welcomepage.welcomepage_users 
where team_id = 26 and is_draft = false;

select auth_email, auth_role, welcomepage_users.* 
from welcomepage.welcomepage_users
join welcomepage.teams on teams.id = welcomepage_users.team_id
where teams.public_id = 'juhg34g2k9';

select * 
from welcomepage.welcomepage_users 
where slack_user_id = 'U09KBMDENMN';

select is_draft, * 
from welcomepage.welcomepage_users 
where public_id = '0bmntxfqao';

select team_id, slack_user_id, auth_email, auth_role, * 
from welcomepage.welcomepage_users  
order by id desc;

select * 
from welcomepage.welcomepage_users 
where public_id = '0bmntxfqao';

select * 
from welcomepage.welcomepage_users 
where public_id = '0bmntxfqao'  
order by id desc;

select auth_email, auth_role, * 
from welcomepage.welcomepage_users 
where auth_email = 'charles.barton+100@gmail.com';

select auth_email, auth_role, * 
from welcomepage.welcomepage_users 
where auth_email like 'charles.barton+9%@gmail.com';

update welcomepage.welcomepage_users 
set auth_role = 'USER' 
where auth_email like 'charles.barton+9%@gmail.com';

select 
    auth_email, 
    auth_role,
    name,
    CASE 
        WHEN auth_email IS NULL THEN 'Missing Email'
        WHEN auth_email = '' THEN 'Empty Email'
        WHEN auth_role NOT IN ('USER', 'ADMIN') THEN 'Wrong Role: ' || auth_role
        ELSE 'Included'
    END as filter_reason
from welcomepage.welcomepage_users
join welcomepage.teams on teams.id = welcomepage_users.team_id
where teams.public_id = 'ied3vv24li'
ORDER BY filter_reason;

SELECT
  t.public_id AS team_public_id,
  u.auth_email,
  u.public_id AS user_public_id,
  u.auth_role,
  u.slack_user_id,
  u.name,
  u.id
FROM welcomepage.welcomepage_users AS u
JOIN welcomepage.teams AS t ON u.team_id = t.id
WHERE u.auth_email LIKE 'charles.barton%@gmail.com'
ORDER BY u.id DESC;

select auth_email, * 
from welcomepage.welcomepage_users 
where auth_email like 'charles.barton%@gmail.com'
order by auth_email;

select * 
from welcomepage.verification_codes 
order by id desc;

---------------------------
--- TEAMS QUERIES ---------
---------------------------

select * 
from welcomepage.teams where id = 130
order by organization_name 

select * 
from welcomepage.teams 
where organization_name like 'IBM%';

select sharing_settings, * 
from welcomepage.teams 
where public_id = 'bgs-team01';

select subscription_status, * 
from welcomepage.teams 
where subscription_status IS NOT NULL 
order by id;

SELECT *
FROM welcomepage.teams
WHERE custom_prompts IS NOT NULL
order by id;

SELECT sharing_settings, *
FROM welcomepage.teams
WHERE sharing_settings IS NOT NULL;

SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'slack_pending_installs';

select * 
from welcomepage.slack_pending_installs;

select * 
from welcomepage.welcomepage_users 
order by id 
where public_id = 'bu9vx6reqt';

select public_id 
from welcomepage.welcomepage_users;

select organization_name, public_id, id 
from welcomepage.teams;

UPDATE welcomepage.welcomepage_users
SET public_id = LEFT(public_id, 10)
WHERE length(public_id) > 10;

select * 
from welcomepage.page_visits;

-- Search
SELECT id, name, role, location
FROM welcomepage.welcomepage_users
WHERE search_vector @@ plainto_tsquery('toronto') 
  AND team_id = 26;

SELECT id, name, role, auth_email, auth_role
FROM welcomepage.welcomepage_users
WHERE search_vector @@ plainto_tsquery('toronto') 
  AND team_id = 26
  AND (auth_email IS NULL OR auth_email = '' OR auth_role NOT IN ('USER', 'ADMIN'));

------- profiling
SELECT relname, seq_scan, idx_scan, seq_tup_read, idx_tup_fetch
FROM pg_stat_user_tables
ORDER BY seq_scan DESC
LIMIT 20;

SELECT calls, round(total_exec_time::numeric,2) AS total_ms,
       round(mean_exec_time::numeric,2) AS avg_ms,
       rows, shared_blks_read, shared_blks_hit, queryid, query
FROM pg_stat_statements
WHERE query ILIKE '%welcomepage_users%'
ORDER BY calls DESC
LIMIT 20;

SELECT pid, query
FROM pg_stat_activity
WHERE query ILIKE '%welcomepage_users%'
  AND state = 'active';

SELECT version();

SELECT query
FROM pg_stat_statements
WHERE queryid = '-3558060556423766990';

----------------------------------------------------------------------
-- Supporting table queries
----------------------------------------------------------------------

select * 
from welcomepage.page_visits 
order by visit_start_time desc;

select * 
from welcomepage.slack_pending_installs;

select * 
from welcomepage.alembic_version;

----------------------------------------------------------------------
SELECT id, team_id, is_draft
FROM welcomepage.welcomepage_users
WHERE auth_email = 'charles.barton+2000@gmail.com'
  AND team_id IS NOT NULL;

----------------------------------------------------------------------
-- DELETE sequence
----------------------------------------------------------------------

BEGIN;

CREATE TEMP TABLE target_users 
ON COMMIT DROP AS
SELECT id, team_id
FROM welcomepage.welcomepage_users
WHERE auth_email = 'charles.barton+2000@gmail.com'
  AND team_id IS NOT NULL;

DELETE FROM welcomepage.welcomepage_users wu
USING target_users tu
WHERE wu.id = tu.id;

DELETE FROM welcomepage.teams t
USING (SELECT DISTINCT team_id FROM target_users) du
WHERE t.id = du.team_id
  AND NOT EXISTS (
      SELECT 1 
      FROM welcomepage.welcomepage_users wu2
      WHERE wu2.team_id = t.id
  );

COMMIT;


select auth_email, team_id, is_draft, * from welcomepage.welcomepage_users where auth_email like '%@a2xaccounting.com'
-- select auth_email, is_draft, slack_id, * from welcomepage.welcomepage_users where team_id = 43
-- select auth_email, team_id, is_draft, * from welcomepage.welcomepage_users where auth_email = 'mark@a2xaccounting.com'
-- select * from welcomepage.teams where id = 134
-- SELECT
--     COUNT(*) FILTER (WHERE is_draft = TRUE)  AS draft_count,
--     COUNT(*) FILTER (WHERE is_draft = FALSE) AS published_count,
--     COUNT(*)                                AS total_count
-- FROM welcomepage.welcomepage_users
-- WHERE team_id = 43;

-- select * from welcomepage.teams where public_id = ''
-- select * from welcomepage.teams where organization_name like 'A2X%'
-- select * from welcomepage.welcomepage_users where  auth_email = 'charles@a2xaccounting.com'
-- select auth_email, team_id, * from welcomepage.welcomepage_users where  public_id = '58fwswna2r'
-- select auth_email,* from welcomepage.welcomepage_users where  auth_email like '%x%'

SELECT auth_email, name, *
FROM welcomepage.welcomepage_users 
WHERE team_id = 43
  AND is_draft = FALSE
  AND (selected_prompts IS NOT NULL OR bento_widgets IS NOT NULL)
ORDER BY RANDOM()
LIMIT 10;