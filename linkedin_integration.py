"""
LinkedIn integration — connect a personal LinkedIn account via OAuth and
post job openings to that person's feed.

IMPORTANT SCOPE NOTE: this posts a normal update to the connected person's
LinkedIn feed (a share, same as clicking "Start a post" on linkedin.com) —
it does NOT create a listing on LinkedIn's actual Jobs board. Posting to
LinkedIn Jobs requires LinkedIn Talent Solutions partnership access, which
is a separate, invite-only commercial relationship Anthropic/this app has
no path to. This feed-post approach only needs LinkedIn's standard,
self-serve Developer Portal access — no special approval beyond requesting
two free "Products" on your app (see setup below).

SETUP (one-time, in LinkedIn's Developer Portal — https://www.linkedin.com/developers/apps):
  1. Create an app (any LinkedIn personal account can do this).
  2. Under "Products", request:
       - "Sign In with LinkedIn using OpenID Connect"  (free, usually instant)
       - "Share on LinkedIn"                            (free, usually instant)
  3. Under "Auth", add this exact redirect URL:
       <your APP_BASE_URL>?linkedin_callback=1
     (must match exactly, including trailing slash behavior — copy it from
     the app's "Connect LinkedIn" button tooltip if unsure.)
  4. Copy the "Client ID" and "Client Secret" into secrets.toml:
       LINKEDIN_CLIENT_ID = "..."
       LINKEDIN_CLIENT_SECRET = "..."
  5. Also make sure APP_BASE_URL is set (same key used for the public apply
     links/QR codes) — this module reuses it for the OAuth redirect.

Token lifetime: LinkedIn access tokens last ~60 days. There's no refresh
token on the standard (non-partner) flow, so after ~60 days the "Connect
LinkedIn" step needs to be repeated. This module doesn't try to silently
auto-renew — it just prompts to reconnect if a post fails on an expired
token.
"""

import os
import time
import threading
import secrets as _secrets_module
import requests
import streamlit as st

import db

_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
_UGC_POST_URL = "https://api.linkedin.com/v2/ugcPosts"

_SCOPES = "openid profile w_member_social"

# CSRF "state" values for the OAuth flow are stored here — at the server
# process level, not in st.session_state — because navigating away to
# LinkedIn's consent screen and being redirected back is a fresh HTTP
# request that Streamlit treats as a brand-new session. Anything stashed in
# st.session_state before the redirect is gone by the time the callback
# arrives, which is exactly what caused the "state mismatch" error: it
# wasn't really a security failure, it was session loss across the redirect.
# This module-level dict survives that because it lives in the running
# Python process, not tied to any one browser session.
# NOTE: this only works correctly if the app runs as a single process/
# instance (true for a typical single Render/Streamlit-Cloud web service).
# If this app is ever horizontally scaled across multiple instances behind
# a load balancer, move this to a shared store (e.g. a Supabase table with
# an expiry column) instead, since each instance would otherwise have its
# own separate copy of this dict.
_pending_oauth_states: dict[str, float] = {}
_pending_oauth_states_lock = threading.Lock()
_OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes — plenty of time to approve on LinkedIn's consent screen


def _stash_oauth_state(state: str) -> None:
    now = time.time()
    with _pending_oauth_states_lock:
        # Opportunistically clear expired entries so this dict doesn't grow
        # unbounded if some connect attempts never complete.
        for k in [k for k, exp in _pending_oauth_states.items() if exp <= now]:
            del _pending_oauth_states[k]
        _pending_oauth_states[state] = now + _OAUTH_STATE_TTL_SECONDS


def _consume_oauth_state(state: str) -> bool:
    """Checks the state is one we actually issued and hasn't expired, and
    removes it (single-use) so the same authorization link can't be reused."""
    with _pending_oauth_states_lock:
        expiry = _pending_oauth_states.pop(state, None)
    return expiry is not None and expiry > time.time()


def _get_secret(name: str) -> str | None:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def is_configured() -> bool:
    return bool(_get_secret("LINKEDIN_CLIENT_ID") and _get_secret("LINKEDIN_CLIENT_SECRET") and _get_secret("APP_BASE_URL"))


def missing_config() -> list[str]:
    """Which required settings are missing, so the UI can say exactly what
    to fix instead of a generic 'not configured' — this is what causes
    LinkedIn's "You need to pass the redirect_uri parameter" error: it means
    APP_BASE_URL specifically wasn't set/read, so the redirect_uri sent to
    LinkedIn came through empty."""
    missing = []
    if not _get_secret("LINKEDIN_CLIENT_ID"):
        missing.append("LINKEDIN_CLIENT_ID")
    if not _get_secret("LINKEDIN_CLIENT_SECRET"):
        missing.append("LINKEDIN_CLIENT_SECRET")
    if not _get_secret("APP_BASE_URL"):
        missing.append("APP_BASE_URL")
    return missing


def _redirect_uri() -> str:
    # Reads APP_BASE_URL directly rather than importing app.py's own
    # _public_app_base_url() helper — app.py is normally run as the
    # entrypoint script (`streamlit run app.py`), and `import app` from here
    # would make Python load and fully re-execute app.py as a second,
    # separate module (distinct from the already-running __main__ instance),
    # re-triggering st.set_page_config() and everything else at the top of
    # that file. Small duplication here is worth avoiding that.
    base = _get_secret("APP_BASE_URL") or ""
    base = base.rstrip("/") + "/" if base else ""
    return f"{base}?linkedin_callback=1" if base else ""


def build_authorization_url() -> str:
    """Generates the LinkedIn consent-screen URL, with a random `state` value
    stashed for CSRF protection (see _stash_oauth_state — without this, a
    malicious link could trick the app into linking an attacker's
    authorization code to this session)."""
    redirect_uri = _redirect_uri()
    if not redirect_uri:
        raise RuntimeError(
            "APP_BASE_URL isn't set (or wasn't picked up after redeploying) — "
            "LinkedIn needs a real redirect_uri, so the connect link can't be built yet."
        )
    state = _secrets_module.token_urlsafe(24)
    _stash_oauth_state(state)
    client_id = _get_secret("LINKEDIN_CLIENT_ID")
    return (
        f"{_AUTH_URL}?response_type=code&client_id={client_id}"
        f"&redirect_uri={requests.utils.quote(redirect_uri, safe='')}"
        f"&scope={requests.utils.quote(_SCOPES)}"
        f"&state={state}"
    )


def handle_oauth_callback(code: str, state: str) -> tuple[bool, str]:
    """Call this when the app detects ?linkedin_callback=1&code=...&state=...
    in the query params. Exchanges the code for an access token, fetches the
    member's identity, and persists the connection. Returns (ok, message)."""
    if not _consume_oauth_state(state):
        return False, (
            "This connection link expired or was already used — click "
            "'Connect LinkedIn' again to get a fresh one."
        )

    client_id = _get_secret("LINKEDIN_CLIENT_ID")
    client_secret = _get_secret("LINKEDIN_CLIENT_SECRET")
    redirect_uri = _redirect_uri()

    try:
        token_resp = requests.post(_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }, timeout=15)
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except Exception as e:
        return False, f"Couldn't exchange the authorization code for a token: {e}"

    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 60 * 24 * 3600)  # seconds; LinkedIn default ~60 days
    if not access_token:
        return False, f"LinkedIn didn't return an access token: {token_data}"

    try:
        userinfo_resp = requests.get(_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
        userinfo_resp.raise_for_status()
        userinfo = userinfo_resp.json()
    except Exception as e:
        return False, f"Connected, but couldn't fetch your LinkedIn profile info: {e}"

    member_sub = userinfo.get("sub")
    member_name = userinfo.get("name", "")
    if not member_sub:
        return False, f"LinkedIn didn't return a member identifier: {userinfo}"

    member_urn = f"urn:li:person:{member_sub}"
    expires_at_iso = _iso_from_now(expires_in)

    if db.is_configured():
        saved = db.save_linkedin_connection(access_token, expires_at_iso, member_urn, member_name)
        if not saved:
            return False, f"Connected to LinkedIn, but couldn't save the connection: {db.get_last_error()}"
    else:
        # No Supabase — fall back to session-only (lost on restart).
        st.session_state["linkedin_connection"] = {
            "access_token": access_token, "expires_at": expires_at_iso,
            "member_urn": member_urn, "member_name": member_name,
        }

    return True, f"Connected as {member_name}."


def _iso_from_now(seconds_from_now: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds_from_now)).isoformat()


def get_connection() -> dict | None:
    if db.is_configured():
        return db.fetch_linkedin_connection()
    return st.session_state.get("linkedin_connection")


def disconnect() -> None:
    if db.is_configured():
        db.delete_linkedin_connection()
    st.session_state.pop("linkedin_connection", None)


def is_connected() -> bool:
    conn = get_connection()
    if not conn or not conn.get("access_token"):
        return False
    expires_at = conn.get("expires_at")
    if expires_at:
        try:
            from datetime import datetime, timezone
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry < datetime.now(timezone.utc):
                return False
        except Exception:
            pass  # unparseable expiry — assume still valid rather than locking the user out
    return True


def post_job_to_linkedin(job_title: str, summary: str, apply_url: str) -> tuple[bool, str]:
    """Posts a feed update (a share, not a Jobs-board listing — see module
    docstring) announcing the job, with the public apply link attached as a
    link preview card."""
    conn = get_connection()
    if not conn or not conn.get("access_token"):
        return False, "LinkedIn isn't connected. Connect it first."

    commentary = f"We're hiring: {job_title}\n\n{summary}\n\nApply here: {apply_url}".strip()

    payload = {
        "author": conn["member_urn"],
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": commentary},
                "shareMediaCategory": "ARTICLE",
                "media": [{
                    "status": "READY",
                    "originalUrl": apply_url,
                    "title": {"text": job_title},
                }],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }

    try:
        resp = requests.post(
            _UGC_POST_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {conn['access_token']}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            timeout=20,
        )
        if resp.status_code == 401:
            return False, "LinkedIn token expired or was revoked — reconnect LinkedIn and try again."
        resp.raise_for_status()
        return True, "Posted to LinkedIn."
    except Exception as e:
        detail = ""
        try:
            detail = f" — {resp.text[:300]}"
        except Exception:
            pass
        return False, f"LinkedIn post failed: {e}{detail}"
