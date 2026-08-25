"""
Company access: no human-facing email, password, or Google login at all —
just a 4-digit access code per organization.

HOW IT ACTUALLY WORKS UNDER THE HOOD:
Supabase's Row Level Security (used to keep each company's candidates/jobs/
interviews private from every other company) is keyed off auth.uid(), which
only exists for a real, logged-in Supabase Auth session. So the app still
needs *some* real account per company to satisfy that — it's just entirely
hidden from the person using the app.

At creation time, each company gets ONE auto-generated, random Supabase
Auth account (a fake internal email + a long random password, neither of
which any human ever sees or types). Those hidden credentials are stored
alongside the company row. When someone enters the correct 4-digit access
code for that company, the app looks up those hidden credentials (only
if the code matches — see get_company_login in migration_companies.sql)
and logs in with them automatically. The access code is the only thing a
human ever needs to know or share.

CREATE FLOW:
  create_company(name, ...) -> generates hidden credentials, creates the
  Supabase Auth account, creates the companies row (with a random 4-digit
  access_code), logs the creator in immediately. Returns the access code
  to show once on screen.

ENTER FLOW (returning users, via the Choose Company picker):
  enter_company_with_code(company_id, code) -> looks up the hidden
  credentials via the get_company_login() database function (which only
  returns them if the code matches), logs in with them, done.

REQUIRED SUPABASE SETUP: run migration_companies.sql. No email-related
dashboard settings are needed at all — this app never sends or requires
any confirmation email for auth purposes.
"""

import base64
import random
import secrets
import string
import time
import uuid
import streamlit as st
import db


def _with_retry(fn, attempts: int = 3, delay: float = 0.6):
    """
    Retries a network call a couple of times on transient connection errors
    (connection reset, timeout, etc — e.g. Windows' 'WinError 10054: An
    existing connection was forcibly closed by the remote host') before
    giving up. These are almost always one-off network blips, not real
    failures, and a short automatic retry recovers from them silently
    instead of showing the person an error for something that would have
    just worked a second later.
    """
    last_error = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            transient = any(s in msg for s in (
                "10054", "connection", "reset", "timed out", "timeout",
                "broken pipe", "temporarily unavailable", "econnreset",
            ))
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(delay * (attempt + 1))
    raise last_error


def _generate_access_code(length: int = 4) -> str:
    """The only credential a human ever sees — shown once at creation,
    shareable with a team, entered on the Choose Company screen to get in."""
    return "".join(random.choices(string.digits, k=length))


def _generate_internal_credentials() -> tuple[str, str]:
    """A fake email + long random password for the hidden per-company
    Supabase Auth account. Never shown to, or typed by, any human."""
    email = f"org-{uuid.uuid4().hex}@internal.icd-platform.invalid"
    password = secrets.token_urlsafe(24)
    return email, password


def _client():
    return db._get_client()


def _sign_in_internal(email: str, password: str) -> tuple[bool, str]:
    """Establishes a real Supabase session using the hidden per-company
    credentials — never called with anything a human typed."""
    client = _client()
    if client is None:
        return False, "Database isn't configured — add SUPABASE_URL and SUPABASE_KEY to secrets.toml first."
    try:
        result = _with_retry(lambda: client.auth.sign_in_with_password({"email": email, "password": password}))
        if result and result.user:
            st.session_state.auth_user = {"id": result.user.id, "email": result.user.email}
            return True, "Logged in."
        return False, "Login failed."
    except Exception as e:
        msg = str(e)
        if "Email not confirmed" in msg:
            return False, ("Couldn't log in because Supabase is still requiring email confirmation. "
                            "This app uses generated internal accounts with no real inbox behind them, "
                            "so that setting must be off. In the Supabase dashboard, go to "
                            "Authentication -> Providers -> Email and turn OFF \"Confirm email\".")
        return False, f"Couldn't log in: {msg}"


def sign_out():
    client = _client()
    if client:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    keys_to_clear = ["auth_user", "auth_company"]
    for key in keys_to_clear:
        st.session_state.pop(key, None)


def list_companies(search: str = "") -> list[dict]:
    """Lists companies for the 'Choose Company' picker — reads from the
    companies_public view (name/logo/industry only, nothing sensitive), so
    this works even before anyone has entered a code. Returns [] on any
    error rather than raising, since a picker with no results should just
    show 'no matches', not crash the screen."""
    client = _client()
    if client is None:
        return []
    try:
        q = client.table("companies_public").select("*").order("name")
        if search.strip():
            q = q.ilike("name", f"%{search.strip()}%")
        result = q.limit(25).execute()
        return result.data or []
    except Exception:
        return []


def get_company_by_id(company_id: str) -> dict | None:
    """Looks up a single company from the safe companies_public view by id —
    used when a collaborator card is clicked so we can jump straight to the
    access-code screen for that org, the same as picking it from search."""
    client = _client()
    if client is None or not company_id:
        return None
    try:
        result = client.table("companies_public").select("*").eq("id", company_id).limit(1).execute()
        rows = result.data or []
        return rows[0] if rows else None
    except Exception:
        return None


def create_company(name: str, logo_bytes: bytes | None, website: str = "",
                    industry: str = "", company_size: str = "") -> tuple[bool, str]:
    """
    Creates a brand-new organization end to end: generates hidden internal
    login credentials, creates the underlying Supabase Auth account, saves
    the companies row (with a fresh 4-digit access code), and logs the
    creator straight in. No email or password is ever asked of the human.
    """
    client = _client()
    if client is None:
        return False, "Database isn't configured — add SUPABASE_URL and SUPABASE_KEY to secrets.toml first."
    if not name.strip():
        return False, "Organization name is required."

    internal_email, internal_password = _generate_internal_credentials()
    try:
        _with_retry(lambda: client.auth.sign_up({"email": internal_email, "password": internal_password}))
    except Exception as e:
        msg = str(e)
        if "sending confirmation" in msg.lower() or "error sending" in msg.lower():
            return False, ("Couldn't create the organization because Supabase is still trying to send a "
                            "confirmation email — but this app uses generated internal accounts with no real "
                            "inbox, so that will always fail. Fix: in the Supabase dashboard, go to "
                            "Authentication -> Providers -> Email and turn OFF \"Confirm email\", then try again.")
        return False, f"Couldn't set up the organization account: {msg}"

    ok, msg = _sign_in_internal(internal_email, internal_password)
    if not ok:
        return False, f"Organization account created but couldn't log in: {msg}"

    try:
        logo_b64 = base64.b64encode(logo_bytes).decode("ascii") if logo_bytes else None
        access_code = _generate_access_code()
        row = {
            "owner_user_id": st.session_state.auth_user["id"], "name": name.strip(), "logo_base64": logo_b64,
            "website": website.strip(), "industry": industry, "company_size": company_size,
            "access_code": access_code,
            "internal_auth_email": internal_email, "internal_auth_password": internal_password,
        }
        result = _with_retry(lambda: client.table("companies").insert(row).execute())
        if result.data:
            st.session_state.auth_company = result.data[0]
            return True, "Organization created."
        return False, "Couldn't save organization details."
    except Exception as e:
        return False, f"Couldn't save organization: {e}"


def enter_company_with_code(company_id, code: str) -> tuple[bool, str]:
    """
    The entire 'login' flow for a returning visitor: looks up the
    company's hidden credentials via the get_company_login() database
    function, which only returns them if the code matches — then logs in
    with them automatically. If the code is wrong, no credentials come
    back at all, so there's nothing to log in with.
    """
    client = _client()
    if client is None or not code.strip():
        return False, "Enter the access code."
    try:
        result = _with_retry(lambda: client.rpc("get_company_login", {"p_company_id": company_id, "p_code": code}).execute())
        rows = result.data or []
        if not rows:
            return False, "That code doesn't match this organization — check with your admin and try again."
        if not rows[0].get("auth_email") or not rows[0].get("auth_password"):
            return False, ("This organization was created before the current login system and has no "
                            "internal account set up — it can't be logged into anymore. You'll need to "
                            "recreate it via \"Create Organization\".")
        return _sign_in_internal(rows[0]["auth_email"], rows[0]["auth_password"])
    except Exception as e:
        return False, f"Couldn't verify that code: {e}"


def update_company(company_id, updates: dict) -> tuple[bool, str]:
    """Updates the current company's editable details (name, logo, website,
    industry, size). RLS already restricts this to the company's own owner."""
    client = _client()
    if client is None or not company_id:
        return False, "Not logged in."
    try:
        result = _with_retry(lambda: client.table("companies").update(updates).eq("id", company_id).execute())
        if result.data:
            st.session_state.auth_company = result.data[0]
        else:
            st.session_state.auth_company = {**st.session_state.get("auth_company", {}), **updates}
        return True, "Saved."
    except Exception as e:
        return False, f"Couldn't save changes: {e}"


def get_company_for_current_user() -> dict | None:
    """Fetches (and caches in session_state) the company row for whoever is
    currently logged in. Returns None if not logged in or no company yet."""
    if "auth_company" in st.session_state:
        return st.session_state.auth_company
    client = _client()
    user = st.session_state.get("auth_user")
    if client is None or not user:
        return None
    try:
        result = client.table("companies").select("*").eq("owner_user_id", user["id"]).limit(1).execute()
        if result.data:
            st.session_state.auth_company = result.data[0]
            return result.data[0]
        return None
    except Exception:
        return None


def is_logged_in() -> bool:
    return bool(st.session_state.get("auth_user"))
