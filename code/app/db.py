"""Engine/session setup. Local runs use SQLite; on Render, DATABASE_URL
points to PostgreSQL (Render's disk is not persistent, so a file DB would
be wiped on every deploy — PRD section 12).

Phase 186 (RLS H4, SECURITY.md step 3): every Postgres transaction
runs with the caller's identity in two session variables the RLS
policies in code/migrations/phase164_rls.sql read:
  SET LOCAL app.current_user_id = '<telegram id>';
  SET LOCAL app.is_admin = 'true' | 'false';
Without them the policies deny everything (fail closed). The identity
lives in a contextvar (one per request/task) and is applied two ways:
(a) an after_begin listener re-applies it at the start of EVERY
transaction — SET LOCAL dies at COMMIT, so applying it once per
session would silently lose it after the first commit in a request;
(b) apply_rls_context(db) for code that binds the identity while a
transaction is already open (current_user resolves the member
through the same session it then binds). On SQLite both paths are
no-ops, so the suites keep passing unchanged. Every direct
SessionLocal() call site in the app goes through rls_session() or
system_session() below — grep SessionLocal() outside this file to
audit completeness."""
import contextvars
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session as _SASession
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import OFFICIAL_ID, settings

url = settings.DATABASE_URL
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+psycopg://", 1)
elif url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

# --- Phase 186: RLS identity -------------------------------------------
# One identity per task: (telegram_id, is_admin). None means "no
# identity bound yet" — the policies' anonymous view (public posts
# only, no DMs, no notifications). A task that forgets to bind
# degrades to that view; it can never see another member's rows.
_RLS_CTX = contextvars.ContextVar("nexora_rls", default=None)


def is_admin_id(user_id):
    """True when the app already trusts this id to moderate anything:
    ADMIN_IDS, plus MODERATOR_IDS (reports / removals / bans — the
    app lets a moderator remove any post, so the RLS admin bypass
    must not hide reported content from them)."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    return uid in settings.ADMIN_IDS \
        or uid in settings.MODERATOR_IDS


def set_rls_context(user_id, is_admin=False):
    """Bind the current task to a member identity (None clears it).
    Values are coerced here, so the SQL below is always int/bool
    literals and can never carry injected text."""
    if user_id is None:
        _RLS_CTX.set(None)
    else:
        _RLS_CTX.set((int(user_id), bool(is_admin)))


def set_rls_context_for(user_id):
    """Bind to a member, deriving the admin bypass from ADMIN_IDS /
    MODERATOR_IDS (see is_admin_id)."""
    set_rls_context(user_id, is_admin=is_admin_id(user_id))


def set_system_rls_context():
    """Bind to the system identity: the official account id with
    the admin bypass. Background jobs (sweeper, auto-backup) and
    internal writes (security log, maintenance flag) run as the
    system, never as a member and never with an empty id."""
    set_rls_context(OFFICIAL_ID, is_admin=True)


def get_rls_context():
    return _RLS_CTX.get()


def clear_rls_context():
    _RLS_CTX.set(None)


def _rls_statements(ctx):
    uid, admin = ctx
    return (f"SET LOCAL app.current_user_id = '{uid}'",
            "SET LOCAL app.is_admin = 'true'"
            if admin else "SET LOCAL app.is_admin = 'false'")


def _is_postgres_session(session):
    try:
        bind = session.get_bind()
    except Exception:
        return False
    return bind is not None and bind.dialect.name == "postgresql"


def apply_rls_context(db):
    """Apply the current task's identity to db's open transaction
    (Postgres only; no-op on SQLite and when no identity is set).
    Call after binding the identity on a session whose transaction
    is already open — the after_begin listener below only fires
    when a NEW transaction begins."""
    ctx = _RLS_CTX.get()
    if ctx is None or not _is_postgres_session(db):
        return
    for stmt in _rls_statements(ctx):
        db.execute(text(stmt))


def _rls_after_begin(session, transaction, connection):
    """Re-apply the task identity at the start of every transaction.
    SET LOCAL is scoped to one transaction, so a COMMIT anywhere in
    a request would otherwise drop the identity and every later
    query in that request would hit the fail-closed policies."""
    ctx = _RLS_CTX.get()
    if ctx is None:
        return
    try:
        dialect = connection.engine.dialect.name
    except Exception:
        try:
            dialect = session.get_bind().dialect.name
        except Exception:
            return
    if dialect != "postgresql":
        return
    for stmt in _rls_statements(ctx):
        connection.exec_driver_sql(stmt)


event.listen(_SASession, "after_begin", _rls_after_begin)


@contextmanager
def rls_session(user_id=None, is_admin=None):
    """Open a SessionLocal bound to one identity, restoring the
    previous context afterwards. user_id=None means the system
    identity (official id + admin bypass); is_admin=None derives
    it from ADMIN_IDS / MODERATOR_IDS. This is the ONLY way
    application code opens a session directly."""
    token = _RLS_CTX.set(
        (OFFICIAL_ID, True) if user_id is None
        else (int(user_id),
              is_admin_id(user_id) if is_admin is None
              else bool(is_admin)))
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        _RLS_CTX.reset(token)


@contextmanager
def system_session():
    """Open a SessionLocal bound to the system identity (see
    set_system_rls_context). For background jobs and internal
    writes that act for the platform, not for any member."""
    with rls_session() as db:
        yield db


def get_db():
    db = SessionLocal()
    try:
        # A context bound before the session was created (bot
        # handlers, background jobs) applies here; request
        # sessions pick theirs up in current_user instead.
        apply_rls_context(db)
        yield db
    finally:
        db.close()
