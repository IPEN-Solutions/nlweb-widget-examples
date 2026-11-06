-- fastapi-nlweb-widget PostgreSQL + pgvector bootstrap.
-- Run once per database. Requires pgvector to be installed on the server.
CREATE EXTENSION IF NOT EXISTS vector;
