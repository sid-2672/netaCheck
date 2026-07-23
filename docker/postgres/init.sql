-- PostgreSQL initialization script
-- Creates test database for CI environment

CREATE DATABASE netacheck_test
    WITH
    OWNER = netacheck
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8'
    TEMPLATE = template0;

GRANT ALL PRIVILEGES ON DATABASE netacheck_test TO netacheck;

-- Enable pg_trgm extension for full-text search (Phase 9)
\c netacheck
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

\c netacheck_test
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
