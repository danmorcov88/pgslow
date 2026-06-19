-- pgslow demo workload
-- ---------------------------------------------------------------------------
-- Seeds a biggish table and issues a deliberate mix of fast and slow queries
-- so that `pgslow top` and the HTML report have meaningful data: a heavy
-- seq-scan aggregate, a join with poor cache locality, a sort that spills to
-- temp, an unstable query (varying selectivity), and cheap point lookups.
--
-- Statements are issued directly (no DO/PERFORM wrappers) so every entry in
-- pg_stat_statements is a real, EXPLAIN-able query — the way an application
-- would actually hit the database. A few are repeated to build call counts.
--
-- Run after the demo Postgres is up:
--   psql "$PGSLOW_DSN" -f examples/workload.sql
-- ---------------------------------------------------------------------------

SELECT pg_stat_statements_reset();

-- ---------------------------------------------------------------------------
-- Seed data
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    id   int PRIMARY KEY,
    name text,
    plan text
);

INSERT INTO users (id, name, plan)
SELECT g,
       'user_' || g,
       (ARRAY['free', 'pro', 'enterprise'])[1 + (g % 3)]
FROM generate_series(1, 5000) AS g;

-- events has NO secondary indexes on purpose: the filters below hit seq scans.
CREATE TABLE events (
    id         bigint,
    user_id    int,
    kind       text,
    amount     numeric(10, 2),
    created_at timestamptz
);

INSERT INTO events (id, user_id, kind, amount, created_at)
SELECT g,
       1 + (random() * 4999)::int,
       (ARRAY['click', 'view', 'purchase', 'signup', 'error'])[1 + (g % 5)],
       (random() * 500)::numeric(10, 2),
       now() - (random() * interval '90 days')
FROM generate_series(1, 500000) AS g;

ANALYZE users;
ANALYZE events;

-- ---------------------------------------------------------------------------
-- 1. Heavy seq-scan aggregate. No index on amount/kind -> full scan each call.
--    Repeated to accumulate the largest total time.
-- ---------------------------------------------------------------------------
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;
SELECT kind, count(*), avg(amount) FROM events WHERE amount > 250 GROUP BY kind;

-- ---------------------------------------------------------------------------
-- 2. Join with poor cache locality: scans all events, probes users by user_id.
-- ---------------------------------------------------------------------------
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;
SELECT u.plan, count(*), sum(e.amount) FROM events e JOIN users u ON u.id = e.user_id GROUP BY u.plan;

-- ---------------------------------------------------------------------------
-- 3. Sort that spills to temp. Tiny work_mem forces a full external sort of
--    500k rows -> temp_blks_written > 0 (the temp-spill flag).
-- ---------------------------------------------------------------------------
SET work_mem = '64kB';
SELECT user_id, created_at FROM events ORDER BY created_at DESC, user_id;
SELECT user_id, created_at FROM events ORDER BY created_at DESC, user_id;
SELECT user_id, created_at FROM events ORDER BY created_at DESC, user_id;
SELECT user_id, created_at FROM events ORDER BY created_at DESC, user_id;
SELECT user_id, created_at FROM events ORDER BY created_at DESC, user_id;
SELECT user_id, created_at FROM events ORDER BY created_at DESC, user_id;
RESET work_mem;

-- ---------------------------------------------------------------------------
-- 4. Unstable query: a median over a widely varying row count. The ordered-set
--    aggregate must sort the matched rows, so cost swings with the threshold
--    (~5k rows vs ~495k rows) -> high stddev (the `var` flag).
-- ---------------------------------------------------------------------------
-- Mostly cheap (few rows), with a couple of expensive full-table calls -> a
-- heavy-tailed runtime distribution, so stddev exceeds the mean.
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 492;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 488;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 495;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 490;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 485;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 493;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 5;
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) FROM events WHERE amount > 8;

-- ---------------------------------------------------------------------------
-- 5. Cheap point lookups on the primary key: fast, well-cached, tiny total.
-- ---------------------------------------------------------------------------
SELECT * FROM users WHERE id = 42;
SELECT * FROM users WHERE id = 1009;
SELECT * FROM users WHERE id = 3333;
SELECT * FROM users WHERE id = 77;
SELECT * FROM users WHERE id = 4821;
SELECT * FROM users WHERE id = 256;

-- Done. Inspect with:  pgslow top --limit 15
