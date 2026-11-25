# Nexora Social — Security Documentation (Phase 28, 1 Nov 2026)

What protects the platform today, what is partial, and what is not
implemented — with the test evidence for each claim. The pre-fix
audit is in SECURITY_AUDIT.md. Nothing here claims 100% security;
every "Implemented" line names how it was verified.

Status key: ✅ Implemented & tested · 🟡 Partially implemented ·
❌ Not implemented · N/A — not applicable to this architecture.

## 1. Telegram authentication
- ✅ initData HMAC-SHA256 signature validated server-side on every
  request (timing-safe compare); `initDataUnsafe` never trusted.
- ✅ **auth_date freshness**: initData older than 24h
  (`INITDATA_MAX_AGE_SECONDS`) or dated >5 min in the future is
  rejected — a captured string no longer works forever.
  Tested: test_phase28 (expired 401, future 401, fresh 200).
- 🟡 **Replay protection**: bounded by the 24h freshness window and
  by revocation (below). Telegram's model is stateless — the same
  initData legitimately rides every request of a session — so
  per-request nonce rejection is not possible without breaking the
  Mini App. Residual risk: a string stolen AND used within 24h.
- ✅ Bot token exists only in server env vars; never in frontend
  code, URLs, or logs.
- 🟡 Sessions: the design is stateless (no server-side session
  store), so there is nothing to expire or rotate — BUT
  **revocation is implemented**: `users.auth_revoked_at` +
  `POST /admin/users/{id}/revoke-sessions` kills every initData a
  member received before that moment; reopening the app restores
  access with fresh data. Tested: test_phase28.

## 2. Authorization & access control
- ✅ Server-side authorization on every endpoint
  (`current_user` / `admin_user` / `moderator_user` dependencies);
  ownership checks on destructive actions (post delete = owner only;
  account delete = self only, never while acting as another account).
- ✅ IDOR posture: member data endpoints are keyed to the caller's
  own id; admin reads are role-gated. Tested across suites
  (member → admin routes = 403, verified Phases 18–28).
- ✅ **RBAC tiers**: Super Admin (`ADMIN_IDS`: everything), Admin —
  the same env list is the platform's admin tier today, Moderator
  (`MODERATOR_IDS`: reports, comment/post removal, bans — NOT
  points, verify grants, profile edits, member deletion, broadcast,
  managed users, audit log), User. Tested: test_phase28.
- ✅ Re-authentication for sensitive actions: self-delete requires
  a typed `DELETE` confirmation; admin mutations (Phase 164) need
  initData no older than 5 minutes — a stale admin session is told
  to reopen the app. There is no password to re-check (Telegram
  auth), so step-up freshness is the equivalent control.
- ✅ Act-as remains admin-only and can never target a real member.

## 3. API security
- ✅ HTTPS enforced at the Render edge; HSTS header sent.
- ✅ Strict input validation: pydantic models with length caps on
  every text field (captions 2000, comments 1000, reports 256,
  broadcast 4000, names 128, bios 1000); unknown/mass-assignment
  fields are dropped by the models. Tested: test_phase28 (422s).
- ✅ Parameterized queries everywhere (SQLAlchemy ORM; the single
  raw `text()` is a hardcoded migration).
- ✅ **Rate limiting** per user per action (posts 30/h, comments
  120/h, likes 600/h, follows 200/h, reports 30/day, uploads 30/h,
  shares 120/h, searches 240/h, media 60/min) and per IP on `/auth`
  (120/min), answering 429 + `Retry-After`. The per-IP key uses the
  LAST X-Forwarded-For hop (Phase 164) — the first hop is
  client-spoofable. In-memory (single instance); must move to a
  shared store if the service scales out. Tested: test_phase28/164.
- ✅ Request-size limits: uploads are read with a hard streaming
  cap (photo 20 MB / video 60 MB) that aborts mid-read — the body
  is never fully buffered before the check. Tested: test_phase28.
- ✅ CORS: no CORS middleware = same-origin only; the API is not
  readable cross-origin by any website.
- N/A CSRF: authentication is a custom header (`X-Init-Data`), no
  cookies are used, so classic CSRF does not apply.
- ✅ Security headers on every response: CSP (strict script
  sources; framing restricted to Telegram's web clients via
  `frame-ancestors`), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`, `Permissions-Policy`, HSTS.
  Tested: test_phase28.
- ✅ Idempotency: upload dedupe by `X-Upload-Id` (Phase 27);
  like/follow/save toggles are naturally idempotent; daily-task
  claims are unique-constrained.
- ✅ Secure errors: clients receive generic messages; the global
  handler logs the detail server-side. No stack traces, no secrets
  in responses.

## 4. Web attack protection
- ✅ SQL injection: ORM parameterization (above).
- ✅ XSS: the frontend builds UI with `createElement`/`textContent`
  (188 uses); `innerHTML` only clears containers or inserts static
  strings — stored/reflected/DOM XSS has no sink for user data.
  CSP is the second layer.
- ✅ Clickjacking: CSP `frame-ancestors` limited to Telegram
  (`web.telegram.org`, `*.telegram.org`) and self.
  `X-Frame-Options` is deliberately NOT set — it cannot express
  the Telegram allowlist and would break the Mini App.
- ✅ Open redirects: the app issues no redirects to user-supplied
  URLs; outbound links are built only to t.me with encoded parts.
- ✅ LIKE-wildcard escaping in search (`%`/`_` escaped, M3).
- 🟡 WAF/DDoS: Render edge baseline only; no Cloudflare in front
  (platform decision, not app code).

## 5. User account security
- ✅ Suspension (ban) with immediate effect on every request;
  recovery = admin unban; sessions revocable (§1).
- ✅ Self-service **account deletion** (typed confirmation, full
  wipe — the same routine as admin delete). Tested: test_phase28.
- ✅ Report + moderation workflow; **block implemented**
  (second-pass R5): blocking a member hides both sides' posts and
  profiles from each other, removes follows both ways, and refuses
  new follows/comments/likes/shares between the pair; the blocker
  manages it from the profile or `GET /me/blocked`. Mute is the
  same relation's visibility effect. Tested: test_phase29.
- ✅ Security events logged (§13) without private content.
- 🟡 Account enumeration: profiles are public by design in a
  social app; existence of a Telegram id is not treated as secret.

## 6. Spam & abuse protection
- ✅ Per-action rate limits (§3) cover posts, comments, likes,
  follows, reports, uploads, shares — and, since the second-pass
  audit, the analytics reporters too (`/ads/shown` 60/h on top of
  its 5-second dedupe, `/me/heartbeat` 240/h), and every list
  endpoint is response-capped (comments return the latest 500,
  referrals the newest 200 with a true total). Tested:
  test_phase29.
- ✅ Duplicate protection: upload dedupe, unique constraints on
  likes/follows/saves/claims, referral pays only after the new
  member's first post, likes earn no points (anti-farming).
- ✅ Report queue with moderator review; progressive enforcement =
  warn-by-DM (manual), ban, session revocation.
- ❌ Automated spam detection / anti-bot challenges: not
  implemented; Telegram accounts themselves are the bot barrier
  (a Telegram account is required before any action is possible).

## 7. Database security
- ✅ Render Postgres reached only via the internal connection
  string on Render's private network; not publicly exposed.
- ✅ Credentials only in env vars (`sync: false` in render.yaml);
  nothing secret in source control (verified in audit).
- ✅ Parameterized queries; migrations are additive ALTERs guarded
  by an inspector check (safe to re-run).
- ✅ Points changes are fully ledgered (auditable); admin actions
  are audit-logged (§10).
- N/A Password hashing: no passwords exist (Telegram auth only).
- 🟡 Encryption at rest: provided by Render's managed Postgres
  (platform), not application-level.

- 🟡 **Row Level Security (Phase 164)**: policies + a least-privilege
  `nexora_app` role are written and ready (`code/migrations/phase164_rls.sql`,
  `code/migrations/phase164_rls_role.sql`) but NOT live-enabled —
  enabling needs a Render DATABASE_URL change (owner step, see §16).
  Query-level scoping (§2) remains the live control until then.

## 8. File & media upload security
- ✅ Extension + MIME allowlists AND **actual file-signature
  (magic byte) validation** — content must agree with the claimed
  kind before anything is forwarded. Tested: test_phase28.
- ✅ Size caps enforced during the read (see §3).
- ✅ Dangerous types blocked: only photo/video containers pass;
  executables cannot be classified or forwarded.
- ✅ Media is stored on Telegram's servers — outside the web root,
  never executed, served back through the `/media` proxy.
- ✅ **Media access control**: `/media` requires a user-bound
  1-hour signed token (HMAC over user id + issue time + expiry,
  issued at login, refreshed while the app is open) AND the file
  must be visible to that member — private-account and DM media
  answer 404 to strangers, and revoked sessions' tokens die.
  Rate-limited 60/min per user. Tested: test_phase16/28/164.
- 🟡 Malware scanning: not implemented (no AV engine); mitigated
  by the strict type allowlist + signature check + Telegram's own
  processing, and by media never being executed or rendered as
  anything but image/video.
- 🟡 Metadata: HEIC uploads are re-encoded (EXIF dropped);
  JPEG/PNG are forwarded to Telegram, which re-encodes photos on
  its side. Server-side stripping of every photo is a backlog item.
- ✅ Server-side file names: uploads are renamed before the
  Telegram send in the video pipeline; photos keep no path
  semantics (Telegram file_ids only). No path traversal surface:
  no user-controlled filesystem paths exist.

## 9. Server & infrastructure security
- 🟡 Platform-managed (Render): OS patching, firewall, closed
  ports, least-privilege runtime are Render's layer; the app adds:
- ✅ Secrets in env only; dev/prod separation = local test DBs vs
  the Render DATABASE_URL; no test data in production paths.
- ✅ Dependencies pinned to tested versions (requirements.txt).
- ❌ Infrastructure alerting: not configured (see §13).

## 10. Admin panel security
- ✅ Strict server-side role checks on every admin route (member
  403s verified in Phases 18–28 tests).
- ✅ **Tamper-evident audit log**: `admin_audit_logs` records every
  ban/unban, points adjustment, verify grant/revoke, profile edit,
  member/managed-account deletion, broadcast, report resolution,
  comment/post/design removal, verification decision and session
  revocation — append-only from the app's side, viewable at
  `GET /admin/audit-log` (admins only). Tested: test_phase28.
- ✅ Dangerous actions keep their safety rails: the official
  account cannot be banned, deleted or unverified; an admin cannot
  delete his own account; moderators cannot ban admins, and only
  an admin can ban a moderator.
- ✅ **Maintenance mode** (`MAINTENANCE_MODE=1` env): API answers
  503 while /health stays up. Tested: test_phase28.
- ✅ Admin MFA (Phase 164): two layers. (1) Step-up — mutating
  admin calls need initData no older than 5 minutes. (2) TOTP —
  when `ADMIN_TOTP_SECRET` is set in Render, admin calls need a
  verified 6-digit authenticator code per 12-hour session
  (`GET /admin/totp/setup` enrolls, `POST /admin/totp/verify`
  checks, `pyotp`). Until the secret is set, TOTP is dormant and
  step-up is the live control. Telegram's own two-step verification
  on the owner's account remains a required owner step (§16).

## 11. Privacy & data protection
- ✅ Data collected is minimal: Telegram id/name/username,
  language, one-time IP-approximated country (name only), and
  what members post. IPs are never stored.
- ✅ **Data export**: `GET /me/export` returns the member's own
  profile, posts, comments, points ledger and follow lists.
  Tested: test_phase28.
- ✅ Deletion: self-delete and admin delete wipe every trace
  (posts, engagement, follows, referrals, ledger, activity).
- ✅ Logs never contain initData, tokens, or message content.
- 🟡 A written public privacy policy page: not yet published
  in-app (the practices are documented here).

## 12. Backup & disaster recovery
- ❌ Automated backups: **not available on the free Render
  Postgres plan**. This is the phase's largest platform gap and
  the second reason (after the 2026-11-30 free-DB expiry) for the
  already-planned paid upgrade: the basic plan adds daily backups
  and point-in-time recovery.
- 🟡 Recovery: the codebase + full schema live in GitHub; the app
  recreates its schema on boot. Data recovery before the upgrade
  relies on Render's platform durability only. RPO/RTO are
  therefore "best effort" until backups exist — stated plainly,
  not dressed up.

- ✅ **Backup payload encryption (Phase 164)**: when
  `BACKUP_ENCRYPTION_KEY` is set in Render, every backup (download,
  send-to-Telegram, weekly auto-backup) leaves the server as a
  Fernet-encrypted `.json.enc` file; restore accepts encrypted and
  plaintext. Without the key, backups stay plaintext and the server
  logs a warning. Losing the key makes encrypted backups
  unrestorable — the key lives in Render env only. Tested:
  test_phase164.

## 13. Logging & monitoring
- ✅ Security event log (service logs): rejected initData (with
  client IP at /auth), admin/moderator denials, rate-limit hits,
  admin actions, self-deletions, unhandled errors — never secrets
  or content.
- ✅ Admin audit log (§10) for privileged actions.
- 🟡 Platform monitoring: Render metrics (CPU/RAM/restarts) exist;
  no alert rules or external error tracking configured — backlog.

## 14. Emergency protection
- ✅ Maintenance mode (env flag, §10). ✅ Session revocation (§1).
- ✅ API disable = maintenance mode or stopping the service in
  Render. ✅ Rollback = redeploy any previous commit from Render
  (deploys are commit-based; the previous version is one click).
- ✅ Compromised-credential rotation procedure (owner steps):
  1) Bot token: BotFather → /revoke for @NexoraSocial_bot, paste
  the new token into Render env `BOT_TOKEN`, redeploy. All old
  initData dies with the old token — every member just reopens
  the app. A leaked bot token is a FULL bot compromise until
  rotated: it signs initData, media tokens and QR tokens.
  Verify after rotating: /health answers 200, the Mini App opens,
  and one admin call succeeds.
  2) Database: rotate from the Render dashboard (database →
  credentials), update the service env if not using the internal
  reference, redeploy.
  3) Render/GitHub account credentials: change at the provider;
  enable two-step verification on both and on Telegram.
  4) Sessions: after any rotation, revoke sessions for affected
  members (`POST /admin/users/{id}/revoke-sessions`) — a bot-token
  rotation already kills every initData, so this is belt and
  braces for the database case.
  5) Backup key: if `BACKUP_ENCRYPTION_KEY` ever leaks, generate a
  new Fernet key, set it in Render, and re-take every backup —
  backups encrypted under the old key stay readable to the key
  holder and cannot be re-keyed.

## 15. Security testing
- ✅ test_phase28.py — the security suite: initData expiry/future,
  headers, media-token gate, upload signature + capped read,
  input caps, rate limiting, revocation, audit log, moderator
  boundaries, maintenance mode, export + self-delete.
- ✅ All 26 suites pass (test_smoke + Phases 4–28), including the
  authorization matrices of Phases 18/20/24 (member vs admin 403s =
  IDOR/privilege-escalation coverage) and the upload suites of
  Phases 16/19/26/27.
- 🟡 OWASP ASVS: this phase maps to ASVS areas V2 (auth), V3
  (session — adapted to stateless), V4 (access control), V5
  (validation), V7 (errors/logging), V12 (files), V14 (config) —
  a formal ASVS audit and an external penetration test have NOT
  been performed and are recommended before any payments launch.
- ❌ Backup-restoration test: impossible until backups exist
  (§12). ❌ Load/DDoS testing: not performed on the free tier.

## Owner backlog (in priority order)
1. Paid Render upgrade before 2026-11-30 → enables DB backups
   (§12) and removes free-tier limits; then test a restore.
2. Enable Telegram two-step verification + Render/GitHub 2FA
   (admin MFA equivalent, §10/§14).
3. A public privacy page (§11).
4. External pen test before any money/withdrawal features (§15).
5. If the service ever scales beyond one instance: move rate
   limiting and upload dedupe to a shared store (§3).

## Second-pass addendum (1 Nov 2026)
A read-only re-audit of the post-Phase-28 code (owner's request)
confirmed every Phase 28 control in place and fixed five more
items (R1–R5, detailed in SECURITY_AUDIT.md): comment/referral
list caps, analytics rate budgets, in-memory store pruning, and
member blocking (§5/§6). Evidence: test_phase29 + the full
27-suite run, all green; live checks after deploy repeated the
Phase 28 probes (headers, /media 401, /feed 401) plus the new
client block wiring in the served app.js.

## 16. Phase 164 — 2026-11-21 audit fixes (21 Nov 2026)
A read-only audit of the Phase 162 code against the owner's
20-point checklist found 17 Implemented, 2 Partial, 1 Not
Implemented. Phase 164 fixes every gap (report:
`~/workspace/nexora_designs/security_audit_2026-11-21.md`):
- ✅ P1 (Critical): /media token is user-bound, 1-hour, honours
  revocation, and the handler checks file visibility (same rules
  as the feed) + a 60/min per-user rate limit.
- ✅ H1: admin step-up (5-min fresh initData for mutating /admin/*
  calls) + per-admin TOTP (pyotp, env secret, 12-hour session) +
  the Admin Panel gate in the client.
- ✅ H2: client IP = last X-Forwarded-For hop; /media rate-limited.
- ✅ H3: bot-token rotation runbook (§14).
- 🟡 H4: RLS policies + `nexora_app` role written
  (`code/migrations/phase164_rls.sql`,
  `code/migrations/phase164_rls_role.sql`) — NOT live-enabled.
  Phase 186 (Nov 25, 2026) finished step (3) in code: every DB
  session carries the caller's identity (`SET LOCAL
  app.current_user_id / app.is_admin`) via a contextvar +
  `after_begin` listener in `app/db.py` (SET LOCAL dies at COMMIT,
  so it is re-applied at every transaction begin), bound in
  `current_user` / `/auth` / `/media` / `/p/{id}`, in all 6 bot
  handlers, and as the system identity in the sweeper, auto-backup,
  security log and video-upload job. The role script was fixed to
  grant DML on all 52 current tables (Phase 164 listed 44; the 8
  Phases 170–185 tables were missing). `create_all()` /
  `_migrate()` now survive a permission refusal (42501) at boot
  with a loud log — the app role has no DDL, so migrations become
  an owner-run step. Step (4) was done LOCALLY, not on staging:
  a Postgres 16 scratch DB smoke pass (32/32 probes —
  `~/workspace/nexora_designs/phase186_smoke.py`) verified the
  policy matrix (own/private/DM/admin/no-vars), write denial,
  identity surviving COMMIT, and a clean `app.main` import under
  the app role with RLS live; it also caught two real bugs (the
  permission check read psycopg2's `pgcode` while the app runs
  psycopg3's `sqlstate`, and CREATE TABLE IF NOT EXISTS does fail
  without CREATE privilege). Remaining owner steps, in order:
  (1) create the role with the role script; (2) point the
  service's DATABASE_URL at the `nexora_app` role and confirm the
  app still works; (3) run the policies file as the owner;
  (4) verify with the cross-user probe. Exact commands, rollback
  (`phase186_rollback.sql`) and the role password are in
  `~/workspace/nexora_designs/phase186_production_steps.md`.
  RLS is NOT live on production until those run.
- ✅ M1: Dependabot (`.github/dependabot.yml`, pip, weekly) +
  monthly `pip-audit` run documented; `pip-audit` run 21 Nov 2026:
  no known vulnerabilities.
- 🟡 M2: backup encryption is live in code but dormant until the
  owner sets `BACKUP_ENCRYPTION_KEY` in Render — backups stay
  plaintext until then (logged loudly).
- ✅ L1: the single-instance in-memory limiter assumption was
  already recorded in `ratelimit.py` + §3 — verified, no change.
- ✅ #9 MFA: step-up + TOTP (when the secret is set) + Telegram
  2-Step Verification (owner step) = the implemented equivalent.

Owner steps still open after Phase 164 (do not claim done):
1. Set `BACKUP_ENCRYPTION_KEY` in the Render service env (Muse
   hands over the generated key) — then re-take a backup to get
   the first encrypted one.
2. Set `ADMIN_TOTP_SECRET` in Render (Muse hands over the
   generated secret), then enroll via the Admin Panel's
   "Show setup code" — until then TOTP stays dormant.
3. Turn on Telegram two-step verification on the owner's account.
4. H4 live enablement — the code half is done (Phase 186: session
   variables in every DB session, role script fixed to 52 tables,
   local Postgres smoke pass 32/32). The production half is owner
   steps in `~/workspace/nexora_designs/phase186_production_steps.md`
   (create role → repoint DATABASE_URL → run policies → verify,
   with rollback); only when the owner chooses to. The app is safe
   without it (query-level scoping), and the production database
   expires 2026-11-30 — after any migration to a new database the
   same enablement must be repeated on the new database.
