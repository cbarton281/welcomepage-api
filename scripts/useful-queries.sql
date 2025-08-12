select * from welcomepage_users where auth_email like 'charles.barton+u33@gmail.com'

select auth_email, auth_role, * from welcomepage_users 
where team_id = 1 
order by auth_role 

SELECT 
  teams.public_id AS team_public_id,
  welcomepage_users.auth_email,
  welcomepage_users.public_id AS user_public_id,
  welcomepage_users.auth_role
FROM welcomepage_users
JOIN teams ON welcomepage_users.team_id = teams.id;


select auth_email, * from welcomepage_users where auth_email like 'charles.barton%@gmail.com'
order by auth_email

select * from verification_codes order by id desc

select * from alembic_version

select slack_settings, * from teams where public_id = 'c2b52ea3-bcdf-47fa-a16c-9ef04f31c949'

------------------
