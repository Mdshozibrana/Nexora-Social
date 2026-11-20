-- Phase 164 (H4) — least-privilege application role for Nexora.
--
-- Run ONCE as the database owner (e.g. from the Render dashboard's
-- psql / SQL console), AFTER phase164_rls.sql has been reviewed.
-- Replace <STRONG_PASSWORD> with a long random password and store it
-- in Render as the password part of the service's DATABASE_URL.
-- Replace nexora-db with the real database name if it differs.
--
-- The app role gets ONLY the DML the app needs, on the application
-- tables only. No DDL (no CREATE/ALTER/DROP), no pg_catalog writes,
-- no access to other databases. The owner role stays for migrations
-- only (the app's _migrate() runs at boot — after the switch it must
-- run with the owner connection, or migrations must be applied
-- manually; see SECURITY.md §16).

-- 1. Create the role (idempotent-ish: drop first only if you are
--    sure nothing else uses it).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexora_app') THEN
    CREATE ROLE nexora_app LOGIN PASSWORD '<STRONG_PASSWORD>';
  END IF;
END
$$;

-- 2. Connect + schema usage.
GRANT CONNECT ON DATABASE "nexora-db" TO nexora_app;
GRANT USAGE ON SCHEMA public TO nexora_app;

-- 3. DML on every application table (44 tables, Phase 164).
GRANT SELECT, INSERT, UPDATE, DELETE ON
  ad_events, admin_audit_logs, app_settings, banned_words,
  blood_requests, broadcasts, comment_likes, comments, daily_claims,
  design_likes, design_saves, design_shares, design_views, designs,
  drafts, follow_requests, follows, hashtag_follows, likes,
  message_reactions, messages, notifications, notifications_log,
  payout_requests, points_ledger, poll_options, poll_votes, polls,
  post_shares, post_views, posts, referrals, reports, saved_posts,
  scheduled_posts, security_events, skill_entries, stories,
  story_views, tips, user_activity, user_blocks, users,
  verification_requests
TO nexora_app;

-- 4. Sequences (autoincrement ids) — the app must be able to take
--    the next value and read the current one.
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public
TO nexora_app;

-- 5. No DDL for the app role (belt and braces — a fresh role has
--    no CREATE privilege by default, but say it explicitly).
REVOKE CREATE ON SCHEMA public FROM nexora_app;

-- 6. Verify (run as nexora_app afterwards):
--    SELECT has_table_privilege('nexora_app', 'posts', 'SELECT');
--    SELECT has_table_privilege('nexora_app', 'posts', 'TRUNCATE');
--    -- expect true, then false.
