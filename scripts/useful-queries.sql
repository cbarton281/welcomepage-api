select slack_user_id, team_id, auth_email, * from welcomepage_users order by id desc where public_id = '0bmntxfqao'


-- update welcomepage_users set slack_user_id = null

select team_id, slack_user_id, auth_email, * from welcomepage_users  order by id desc

select * from welcomepage_users where public_id = '0bmntxfqao'

select  * from welcomepage_users where public_id = '0bmntxfqao'  order by id desc

select auth_email, auth_role, * from welcomepage_users 
where team_id = 1 
order by auth_role 

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

select slack_settings, * from teams where public_id = 'ied3vv24li' 

-- 'c2b52ea3-bcdf-47fa-a16c-9ef04f31c949'


SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'slack_pending_installs';

select * from slack_pending_installs


