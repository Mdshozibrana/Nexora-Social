-- Phase 186 rollback — disable RLS and drop every Phase 164 policy.
--
-- Run ONCE as the database owner (see phase186_production_steps.md).
-- Enforcement stops the moment this runs; the app role keeps its
-- DML grants, and the app behaves exactly as it did before RLS.
-- The helper functions (app_uid, app_is_admin, app_author_visible)
-- are left in place deliberately: nothing references them after the
-- policies are gone, and dropping them is optional cleanup.
-- Safe to re-run: every statement is IF EXISTS guarded.

ALTER TABLE posts DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS posts_select ON posts;
DROP POLICY IF EXISTS posts_insert ON posts;
DROP POLICY IF EXISTS posts_update ON posts;
DROP POLICY IF EXISTS posts_delete ON posts;

ALTER TABLE comments DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS comments_select ON comments;
DROP POLICY IF EXISTS comments_insert ON comments;
DROP POLICY IF EXISTS comments_update ON comments;
DROP POLICY IF EXISTS comments_delete ON comments;

ALTER TABLE messages DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS messages_select ON messages;
DROP POLICY IF EXISTS messages_insert ON messages;
DROP POLICY IF EXISTS messages_update ON messages;
DROP POLICY IF EXISTS messages_delete ON messages;

ALTER TABLE notifications DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS notifications_all ON notifications;

ALTER TABLE payout_requests DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS payout_requests_all ON payout_requests;

ALTER TABLE skill_entries DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS skill_entries_select ON skill_entries;
DROP POLICY IF EXISTS skill_entries_write ON skill_entries;

ALTER TABLE blood_requests DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS blood_requests_select ON blood_requests;
DROP POLICY IF EXISTS blood_requests_insert ON blood_requests;
DROP POLICY IF EXISTS blood_requests_write ON blood_requests;
DROP POLICY IF EXISTS blood_requests_delete ON blood_requests;

-- Verify after running (as owner):
--   SELECT count(*) FROM pg_policies WHERE schemaname = 'public';
--   -- expect 0
