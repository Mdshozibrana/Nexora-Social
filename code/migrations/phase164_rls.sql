-- Phase 164 (H4) — Database-level Row Level Security for Nexora.
--
-- READY, NOT LIVE-ENABLED. Do NOT run this against production until
-- the enablement procedure in SECURITY.md §16 is followed in order.
-- The policies mirror the query-level visibility rules the app
-- already enforces; they are defense-in-depth, not a replacement.
--
-- HOW IT WORKS
-- The app must set two session variables per transaction (SET LOCAL
-- in get_db, before any query):
--   SET LOCAL app.current_user_id = '<telegram id>';
--   SET LOCAL app.is_admin = 'true' | 'false';
-- Without them every policy evaluates to "deny" (fail closed).
-- Admins bypass the row checks through the app.is_admin flag —
-- admin reads/writes still go through the app role, never the owner.
--
-- Postgres RLS does NOT apply to the table owner by default, so this
-- file also FORCEs RLS (an owner-role connection stays bound too).
-- The app role itself is created by phase164_rls_role.sql.
--
-- Safe to re-run: every statement is IF NOT EXISTS / DROP IF EXISTS
-- guarded, and no statement alters data.

-- ------------------------------------------------------------------
-- Helpers (in the public schema; SECURITY DEFINER is not needed —
-- they only read the session variables).
-- ------------------------------------------------------------------
CREATE OR REPLACE FUNCTION app_uid() RETURNS bigint
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')::bigint;
$$;

CREATE OR REPLACE FUNCTION app_is_admin() RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT current_setting('app.is_admin', true) = 'true';
$$;

CREATE OR REPLACE FUNCTION app_author_visible(author_id bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  -- Mirrors _can_see_posts + _blocked_by: a private account's rows
  -- are visible only to its followers and itself; a block either
  -- way hides everything.
  SELECT author_id = app_uid()
      OR app_is_admin()
      OR (
        NOT EXISTS (SELECT 1 FROM users u
                    WHERE u.telegram_id = author_id AND u.is_private)
        AND NOT EXISTS (SELECT 1 FROM user_blocks b
                        WHERE (b.blocker_id = author_id
                               AND b.blocked_id = app_uid())
                           OR (b.blocker_id = app_uid()
                               AND b.blocked_id = author_id))
      )
      OR EXISTS (SELECT 1 FROM follows f
                 WHERE f.follower_id = app_uid()
                   AND f.following_id = author_id);
$$;

-- ------------------------------------------------------------------
-- posts
-- ------------------------------------------------------------------
ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE posts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS posts_select ON posts;
CREATE POLICY posts_select ON posts FOR SELECT USING (
  app_is_admin()
  OR user_id = app_uid()
  OR (NOT is_deleted AND app_author_visible(user_id))
);
DROP POLICY IF EXISTS posts_insert ON posts;
CREATE POLICY posts_insert ON posts FOR INSERT
WITH CHECK (app_is_admin() OR user_id = app_uid());
DROP POLICY IF EXISTS posts_update ON posts;
CREATE POLICY posts_update ON posts FOR UPDATE USING (
  app_is_admin() OR user_id = app_uid()
);
DROP POLICY IF EXISTS posts_delete ON posts;
CREATE POLICY posts_delete ON posts FOR DELETE USING (
  app_is_admin() OR user_id = app_uid()
);

-- ------------------------------------------------------------------
-- comments — visible when their post is visible to the viewer
-- (the inner posts query is itself RLS-filtered, so the composition
-- is exact: a comment on an unseen post stays unseen).
-- ------------------------------------------------------------------
ALTER TABLE comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE comments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS comments_select ON comments;
CREATE POLICY comments_select ON comments FOR SELECT USING (
  app_is_admin()
  OR user_id = app_uid()
  OR EXISTS (SELECT 1 FROM posts p WHERE p.id = comments.post_id)
);
DROP POLICY IF EXISTS comments_insert ON comments;
CREATE POLICY comments_insert ON comments FOR INSERT
WITH CHECK (app_is_admin() OR user_id = app_uid());
DROP POLICY IF EXISTS comments_update ON comments;
CREATE POLICY comments_update ON comments FOR UPDATE USING (
  app_is_admin() OR user_id = app_uid()
);
DROP POLICY IF EXISTS comments_delete ON comments;
CREATE POLICY comments_delete ON comments FOR DELETE USING (
  app_is_admin() OR user_id = app_uid()
);

-- ------------------------------------------------------------------
-- messages — participants only (DM photos included).
-- ------------------------------------------------------------------
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS messages_select ON messages;
CREATE POLICY messages_select ON messages FOR SELECT USING (
  app_is_admin()
  OR sender_id = app_uid()
  OR recipient_id = app_uid()
);
DROP POLICY IF EXISTS messages_insert ON messages;
CREATE POLICY messages_insert ON messages FOR INSERT
WITH CHECK (app_is_admin() OR sender_id = app_uid());
DROP POLICY IF EXISTS messages_update ON messages;
CREATE POLICY messages_update ON messages FOR UPDATE USING (
  app_is_admin()
  OR sender_id = app_uid()
  OR recipient_id = app_uid()
);
DROP POLICY IF EXISTS messages_delete ON messages;
CREATE POLICY messages_delete ON messages FOR DELETE USING (
  app_is_admin() OR sender_id = app_uid()
);

-- ------------------------------------------------------------------
-- notifications — owner only.
-- ------------------------------------------------------------------
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS notifications_all ON notifications;
CREATE POLICY notifications_all ON notifications FOR ALL USING (
  app_is_admin() OR user_id = app_uid()
) WITH CHECK (
  app_is_admin() OR user_id = app_uid()
);

-- ------------------------------------------------------------------
-- payout_requests — owner only (admin decides/pays).
-- ------------------------------------------------------------------
ALTER TABLE payout_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE payout_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS payout_requests_all ON payout_requests;
CREATE POLICY payout_requests_all ON payout_requests FOR ALL USING (
  app_is_admin() OR user_id = app_uid()
) WITH CHECK (
  app_is_admin() OR user_id = app_uid()
);

-- ------------------------------------------------------------------
-- skill_entries — directory is public to members whose own profile
-- is visible; writes are owner-only.
-- ------------------------------------------------------------------
ALTER TABLE skill_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE skill_entries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS skill_entries_select ON skill_entries;
CREATE POLICY skill_entries_select ON skill_entries FOR SELECT USING (
  app_is_admin()
  OR user_id = app_uid()
  OR app_author_visible(user_id)
);
DROP POLICY IF EXISTS skill_entries_write ON skill_entries;
CREATE POLICY skill_entries_write ON skill_entries FOR ALL USING (
  app_is_admin() OR user_id = app_uid()
) WITH CHECK (
  app_is_admin() OR user_id = app_uid()
);

-- ------------------------------------------------------------------
-- blood_requests — public to members when the author is visible;
-- writes are author-only (fulfil/cancel) or admin.
-- ------------------------------------------------------------------
ALTER TABLE blood_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE blood_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS blood_requests_select ON blood_requests;
CREATE POLICY blood_requests_select ON blood_requests FOR SELECT USING (
  app_is_admin()
  OR author_id = app_uid()
  OR app_author_visible(author_id)
);
DROP POLICY IF EXISTS blood_requests_insert ON blood_requests;
CREATE POLICY blood_requests_insert ON blood_requests FOR INSERT
WITH CHECK (app_is_admin() OR author_id = app_uid());
DROP POLICY IF EXISTS blood_requests_write ON blood_requests;
CREATE POLICY blood_requests_write ON blood_requests FOR UPDATE USING (
  app_is_admin() OR author_id = app_uid()
);
DROP POLICY IF EXISTS blood_requests_delete ON blood_requests;
CREATE POLICY blood_requests_delete ON blood_requests FOR DELETE USING (
  app_is_admin() OR author_id = app_uid()
);
