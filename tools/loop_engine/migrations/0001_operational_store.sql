CREATE TABLE IF NOT EXISTS review_jobs (
    identity TEXT PRIMARY KEY,
    metadata JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS review_results (LIKE review_jobs INCLUDING ALL);
CREATE TABLE IF NOT EXISTS api_usage (LIKE review_jobs INCLUDING ALL);
CREATE TABLE IF NOT EXISTS loop_events (LIKE review_jobs INCLUDING ALL);
