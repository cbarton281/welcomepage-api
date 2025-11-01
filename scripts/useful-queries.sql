select slack_user_id, team_id, auth_email, is_draft, auth_role, * from welcomepage_users where team_id = 26 order by created_at desc

select auth_email, auth_role, team_id, is_draft,  * from welcomepage_users where  auth_email like 'charles.barton+100@gmail.com'  order by auth_email
select t.* from teams t join welcomepage_users w on t.id = w.team_id where w.auth_email =  'charles.barton+100@gmail.com'

select * from welcomepage_users where slack_user_id = 'U09EX7M3S2F'
-- delete from welcomepage_users where slack_user_id = 'U09EX7M3S2F'

select count(w.*) from welcomepage_users w  where w.is_draft = false and team_id = 26
-- update welcomepage_users w set is_draft = true  where w.is_draft = false and team_id = 26
-- update welcomepage_users w set is_draft = false  where auth_email in ('charles.barton+100@gmail.com', 'charles.barton+200@gmail.com', 'charles.barton+903@gmail.com' ) 

select count(*) from welcomepage_users where team_id = 26 and is_draft = false

select auth_email, auth_role, welcomepage_users.* from welcomepage_users
join teams on teams.id = welcomepage_users.team_id
where teams.public_id = 'juhg34g2k9'

select * from welcomepage_users where slack_user_id = 'U09KBMDENMN'
select is_draft, * from welcomepage_users where public_id = '0bmntxfqao'

-- update welcomepage_users set slack_user_id = null

select team_id, slack_user_id, auth_email, auth_role,* from welcomepage_users  order by id desc

select * from welcomepage_users where public_id = '0bmntxfqao'

select  * from welcomepage_users where public_id = '0bmntxfqao'  order by id desc

select auth_email, auth_role, * from welcomepage_users 
where auth_email = 'charles.barton+100@gmail.com'

select auth_email, auth_role, * from welcomepage_users 
where auth_email like 'charles.barton+9%@gmail.com'

update welcomepage_users set auth_role = 'USER' where auth_email like 'charles.barton+9%@gmail.com'
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
from welcomepage_users
join teams on teams.id = welcomepage_users.team_id
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
FROM welcomepage_users AS u
JOIN teams AS t ON u.team_id = t.id
WHERE u.auth_email LIKE 'charles.barton%@gmail.com'
ORDER BY u.id DESC;

select auth_email, * from welcomepage_users where auth_email like 'charles.barton%@gmail.com'
order by auth_email

select * from verification_codes order by id desc

select * from alembic_version


select * from teams order by public_id
select * from teams where public_id = 'ied3vv24li' 
select * from teams  order by id 
-- update teams set stripe_customer_id = null where public_id = 'ied3vv24li' 

SELECT *
FROM public.teams
WHERE slack_settings->'slack_app' IS NOT NULL;

SELECT sharing_settings,*
FROM public.teams
WHERE sharing_settings IS NOT NULL;

-- 'c2b52ea3-bcdf-47fa-a16c-9ef04f31c949'


SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'slack_pending_installs';

select * from slack_pending_installs

select * from welcomepage_users order by id where public_id = 'bu9vx6reqt'

select public_id from welcomepage_users

select organization_name, public_id, id from teams

UPDATE welcomepage_users
SET public_id = LEFT(public_id, 10)
WHERE length(public_id) > 10;

select * from page_visits
