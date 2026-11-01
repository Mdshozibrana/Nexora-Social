# Nexora Social — Security Audit (Phase 28, 1 Nov 2026)

Audit of the existing application BEFORE changes, against the owner's
15-section security requirements. Every finding cites the code it was
verified in. Fixes were then implemented in the same phase; the final
status table lives in SECURITY.md.

## Already in place (verified in code)

- Telegram initData HMAC-SHA256 signature validation on the server,
  timing-safe compare (`app/security.py`); `initDataUnsafe` is never
  trusted — the client sends raw initData and the server re-verifies
  every request (`app/main.py` `current_user`, `/auth`).
- Bot token exists only in env vars; never in frontend code; the
  `/media` proxy keeps it out of client-visible URLs.
- All database access through the SQLAlchemy ORM (parameterized);
  the only raw `text()` is the `_migrate()` ALTER with a hardcoded
  column dict — no user input.
- Server-side authorization on every endpoint (`Depends(current_user)`);
  admin endpoints gated by `admin_user` (ADMIN_IDS). Post deletion
  checks ownership. Act-as is admin-only and can target only managed
  accounts or the official account — real-member impersonation is
  impossible by design.
- Frontend renders user content with `createElement`/`textContent`
  (188 uses in webapp/app.js); `innerHTML` is used only to clear
  containers or insert static strings — stored XSS is prevented by
  construction, not by filtering.
- Upload allowlists by MIME type + extension, size caps (photo
  20 MB, video 60 MB raw), media stored on Telegram's servers
  (outside the web root, non-executable).
- Ban/unban, report queue with moderation workflow, points ledger as
  an audit trail for points, secrets only from environment
  (render.yaml uses `sync: false` for every secret).
- HTTPS is terminated and enforced by the Render edge.

## CRITICAL

- **C1 — initData never expires.** `validate_init_data` checks the
  signature but never `auth_date`. A captured initData string is a
  permanent credential: replayable forever, from anywhere.
  (Requirements §1: auth_date validation, replay protection.)
- **C2 — No rate limiting anywhere.** No per-user, per-IP or
  per-endpoint limits on posts, comments, likes, follows, reports,
  uploads or `/auth`. One script can flood content, farm engagement
  or spam the moderation queue. (§3, §6.)
- **C3 — Uploads are fully buffered before the size check.**
  `_telegram_upload_or_400` does `data = await file.read()` and only
  then checks the length — a single oversized upload can exhaust the
  free instance's ~512 MB RAM and take the service down. (§3, §8.)

## HIGH

- **H1 — No security headers.** No CSP, no clickjacking protection,
  no `nosniff`, no referrer policy on any response. Note: the fix
  must allow framing by Telegram (`frame-ancestors`) or the Mini App
  itself breaks; `X-Frame-Options: SAMEORIGIN` would be wrong here.
  (§3, §4.)
- **H2 — `/media/{file_id}` is unauthenticated.** Anyone who obtains
  a file_id (a shared screenshot URL, a leaked link) can fetch that
  media forever with no login. File_ids are unguessable, but there
  is no expiry and no access control at all. (§8.)
- **H3 — No file-signature validation.** Upload type is decided by
  the client-supplied MIME type / file extension only
  (`tgupload.classify`). A spoofed file passes until Telegram itself
  rejects it. (§8: validate actual file signature.)
- **H4 — No admin audit log.** Bans, point adjustments, verify
  grants, profile edits, member deletions and broadcasts leave no
  record of which admin did what, or when. (§10, §13.)
- **H5 — No auth revocation short of a ban.** A leaked initData
  cannot be invalidated for one user; the only tool is suspending
  the whole account. (§1 sessions/revocation, §14.)
- **H6 — Unbounded text inputs.** Captions, comments, bios, report
  reasons and broadcast text have no length limits (a few call sites
  trim; the models do not enforce). Storage-abuse and payload-size
  risk. (§3.)

## MEDIUM

- **M1 — RBAC is binary.** ADMIN_IDS (full power) vs member. No
  moderator tier with least-privilege moderation-only access; no
  in-app MFA (admin identity rests entirely on the Telegram
  account). (§2, §10.)
- **M2 — Client-supplied `media_file_id` accepted by POST /posts.**
  A member can attach any bot-known file_id (e.g. another member's
  already-public feed photo) to their own post. The real client
  never does this (media goes through `/posts/upload`); several test
  suites use it as a fixture path. Content-theft risk is covered by
  moderation; recorded as an accepted, documented risk rather than
  breaking the fixture path.
- **M3 — Search LIKE wildcards unescaped** (`%`/`_` in `q` act as
  pattern characters in `/search` and `/admin/users`). (§4.)
- **M4 — No maintenance / emergency mode.** No way to pause the API
  during an incident short of stopping the service. (§14.)
- **M5 — No member data export or self-service account deletion.**
  (§5, §11.)
- **M6 — Failed logins and abuse are not logged.** No security event
  log for rejected initData, 403s on admin routes, or limit hits.
  (§13.)
- **M7 — Photo metadata is forwarded as-is** to Telegram (Telegram
  re-encodes photos on its side; the HEIC path re-encodes via PIL
  and strips EXIF). Partially mitigated by the platform. (§8.)

## LOW / platform-level (cannot be fixed in application code)

- **L1 — Backups.** The free Render Postgres plan has no automated
  backups or point-in-time recovery. §12 is Not Implemented at the
  platform level; the paid upgrade already planned before
  2026-11-30 (DB expiry) is what enables it.
- **L2 — WAF/DDoS.** Only Render's edge baseline; no Cloudflare in
  front. Partially implemented by the platform. (§4, §9.)
- **L3 — Monitoring/alerting.** Render metrics exist; no alerting
  rules or external error tracking configured. (§13.)
- **L4 — Dependency versions unpinned** in requirements.txt.
- **N/A by design:** password hashing (no passwords exist — Telegram
  auth only); CSRF tokens (auth is a custom header, no cookies, so
  classic CSRF does not apply); SQL/NoSQL injection beyond the ORM
  parameterization already in place.
