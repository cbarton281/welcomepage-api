CREATE ROLE welcomepagerole WITH PASSWORD 'wpdev';
ALTER ROLE "welcomepagerole" WITH LOGIN;

GRANT ALL ON DATABASE welcomepage TO welcomepagerole;
GRANT ALL ON DATABASE welcomepage TO postgres;
GRANT CONNECT, TEMPORARY ON DATABASE welcomepage TO PUBLIC;

alter default privileges in schema public grant all on tables to welcomepagerole;
alter default privileges in schema public grant all on sequences to welcomepagerole;

GRANT ALL ON ALL TABLES IN SCHEMA public TO welcomepagerole;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO welcomepagerole;
