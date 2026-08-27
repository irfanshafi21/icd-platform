"""Fast candidate-facing portal with passwordless email OTP authentication."""

from __future__ import annotations

import base64
import html
import json
import os
from urllib.parse import unquote
import streamlit as st

import db


_ACCESS_COOKIE = "icd_candidate_access"
_REFRESH_COOKIE = "icd_candidate_refresh"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30


def _styles() -> None:
    st.html("""
    <style>
    [data-testid="stHeader"], [data-testid="stToolbar"], footer { display:none!important; }
    [data-testid="stAppViewContainer"] { background:
      radial-gradient(circle at 8% 8%,rgba(56,189,248,.16),transparent 28%),
      radial-gradient(circle at 92% 92%,rgba(99,102,241,.11),transparent 30%),
      linear-gradient(145deg,#F8FBFF 0%,#F3F7FC 52%,#F8FAFF 100%); }
    .stMainBlockContainer { max-width:1180px; padding-top:2.5rem; padding-bottom:3rem; }
    .portal-nav { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:13px 18px;
      border:1px solid #DCE6F1; border-radius:18px; background:#fff; box-shadow:0 8px 26px rgba(15,49,74,.07); margin-bottom:22px; }
    .portal-brand img { width:124px; max-height:48px; object-fit:contain; }
    .portal-user { display:flex; align-items:center; gap:10px; color:#475569; font-size:.86rem; font-weight:700; }
    .portal-user-dot { width:10px; height:10px; border-radius:50%; background:#22C55E; box-shadow:0 0 0 4px #DCFCE7; }
    .portal-hero { padding:34px; border-radius:24px; color:#fff; overflow:hidden; position:relative;
      background:linear-gradient(135deg,#0B2A52 0%,#185FA5 58%,#0891B2 100%);
      box-shadow:0 16px 38px rgba(18,49,74,.16); margin-bottom:24px; }
    .portal-hero:after { content:""; position:absolute; width:260px; height:260px; right:-70px; top:-115px;
      border-radius:50%; background:rgba(255,255,255,.10); }
    .portal-hero h1 { margin:0 0 8px; font-size:clamp(1.8rem,4vw,2.7rem); line-height:1.12; }
    .portal-hero p { margin:0; max-width:680px; opacity:.88; line-height:1.55; }
    .portal-eyebrow { font-size:.72rem; text-transform:uppercase; letter-spacing:.14em; font-weight:850; opacity:.8; }
    .job-card { min-height:190px; padding:22px; border:1px solid #DCE6F1; border-top:4px solid #2F80ED; border-radius:18px;
      background:linear-gradient(180deg,#FFFFFF 0%,#F8FBFF 100%); box-shadow:0 8px 24px rgba(15,49,74,.06); transition:transform .18s ease,box-shadow .18s ease; }
    .job-card:hover { transform:translateY(-3px); box-shadow:0 14px 30px rgba(15,49,74,.11); }
    .job-brand { display:flex; align-items:center; gap:12px; min-height:48px; }
    .job-logo { width:48px; height:48px; flex:0 0 48px; object-fit:contain; border-radius:12px; background:#fff;
      padding:5px; border:1px solid #D7E5F4; box-shadow:0 5px 14px rgba(15,49,74,.08); }
    .job-logo-fallback { width:48px; height:48px; flex:0 0 48px; border-radius:12px; background:linear-gradient(145deg,#EAF3FF,#DBEAFE);
      color:#185FA5; display:inline-flex; align-items:center; justify-content:center; font-size:1.05rem; font-weight:850; }
    .job-company { color:#102A43; font-size:.86rem; font-weight:850; line-height:1.25; }
    .job-industry { color:#64748B; font-size:.7rem; margin-top:3px; }
    .job-title { color:#102A43; font-size:1.2rem; font-weight:850; margin:7px 0 9px; }
    .job-meta { color:#64748B; font-size:.82rem; line-height:1.5; min-height:40px; }
    .job-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:14px; min-height:31px; }
    .job-chips span { color:#0C4A6E; background:#E0F2FE; padding:5px 9px; border-radius:999px; font-size:.7rem; font-weight:750; }
    [class*="st-key-candidate_apply_"] button { color:#fff!important; border:0!important; min-height:49px!important;
      border-radius:13px!important; font-weight:780!important; background:linear-gradient(135deg,#2684D8,#0F5F9F)!important;
      box-shadow:0 9px 20px rgba(21,101,173,.18)!important; transition:transform .16s ease,box-shadow .16s ease!important; }
    [class*="st-key-candidate_apply_"] button:hover { transform:translateY(-2px); box-shadow:0 13px 27px rgba(21,101,173,.26)!important; }
    .candidate-applications-head { display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin:8px 0 24px; }
    .candidate-applications-head h2 { margin:0 0 7px;color:#102A43;font-size:1.7rem;letter-spacing:-.025em; }
    .candidate-applications-head p { margin:0;color:#64748B;font-size:.86rem;line-height:1.55; }
    .application-card { display:grid;grid-template-columns:64px minmax(0,1fr) auto;gap:17px;align-items:start;
      padding:22px 23px;margin:0 0 16px;border:1px solid #DCE6F1;border-left:5px solid #2F80ED;border-radius:18px;
      background:linear-gradient(135deg,#FFFFFF 0%,#F6FAFF 100%);box-shadow:0 8px 25px rgba(15,49,74,.065); }
    .application-company-logo { width:58px;height:58px;border:1px solid #D7E5F4;border-radius:15px;background:#fff;
      display:flex;align-items:center;justify-content:center;overflow:hidden;box-shadow:0 5px 14px rgba(15,49,74,.07); }
    .application-company-logo img { width:100%;height:100%;object-fit:contain;padding:7px; }
    .application-company-logo span { color:#1769AA;font-size:1.15rem;font-weight:850; }
    .application-company { color:#1769AA;font-size:.72rem;font-weight:820;text-transform:uppercase;letter-spacing:.09em;margin-bottom:4px; }
    .application-title { color:#102A43;font-size:1.23rem;font-weight:850;line-height:1.25;margin-bottom:9px; }
    .application-meta { display:flex;flex-wrap:wrap;gap:7px 14px;color:#64748B;font-size:.78rem; }
    .application-meta span { display:inline-flex;align-items:center;gap:5px; }
    .application-meta i { font-family:'Material Symbols Rounded';font-style:normal;color:#3B82C4;font-size:16px; }
    .application-resume { margin-top:13px;padding-top:12px;border-top:1px solid #E2EAF3;color:#52627A;font-size:.77rem; }
    .application-resume strong { color:#334155; }
    .application-status { display:inline-flex;align-items:center;gap:6px;padding:7px 11px;border-radius:999px;
      font-size:.72rem;font-weight:800;white-space:nowrap;background:#E6F2FF;color:#0C5E9F;border:1px solid #CDE5FA; }
    .application-status i { font-family:'Material Symbols Rounded';font-style:normal;font-size:16px; }
    .st-key-candidate_auth_value { min-height:560px; padding:42px 40px!important; border-radius:28px!important;
      color:#fff; overflow:hidden; position:relative;
      background:linear-gradient(145deg,#09264B 0%,#124E88 55%,#0788A7 100%)!important;
      box-shadow:0 24px 58px rgba(13,56,96,.22)!important; }
    .st-key-candidate_auth_value:before { content:""; position:absolute; width:290px; height:290px; right:-105px; top:-125px;
      border-radius:50%; border:42px solid rgba(255,255,255,.08); }
    .st-key-candidate_auth_value:after { content:""; position:absolute; width:180px; height:180px; left:-75px; bottom:-80px;
      border-radius:50%; background:rgba(56,189,248,.15); }
    .candidate-auth-logo-wrap { display:inline-flex; padding:10px 14px; border-radius:15px; background:#fff;
      box-shadow:0 10px 24px rgba(2,20,45,.2); margin-bottom:45px; position:relative; z-index:1; }
    .candidate-auth-logo { width:145px; display:block; }
    .candidate-auth-eyebrow { color:#BAE6FD; font-size:.72rem; font-weight:850; letter-spacing:.15em;
      text-transform:uppercase; margin-bottom:13px; position:relative; z-index:1; }
    .candidate-auth-heading { color:#fff; font-family:'Plus Jakarta Sans',sans-serif; font-size:clamp(2rem,3.4vw,3rem);
      font-weight:850; letter-spacing:-.04em; line-height:1.08; margin:0 0 17px; position:relative; z-index:1; }
    .candidate-auth-copy { color:#D9ECFA; font-size:1rem; line-height:1.68; max-width:475px; margin:0 0 28px; position:relative; z-index:1; }
    .candidate-auth-benefits { display:grid; gap:13px; position:relative; z-index:1; }
    .candidate-auth-benefit { display:flex; align-items:center; gap:11px; color:#F4FAFF; font-size:.87rem; font-weight:680; }
    .candidate-auth-benefit-icon { width:28px; height:28px; border-radius:9px; display:flex; align-items:center; justify-content:center;
      background:rgba(255,255,255,.14); color:#BAE6FD; font-family:'Material Symbols Rounded'; font-size:17px; }
    .st-key-candidate_auth_form { min-height:560px; padding:42px 38px 32px!important; border-radius:28px!important;
      background:rgba(255,255,255,.94)!important; border:1px solid rgba(203,213,225,.82)!important;
      box-shadow:0 22px 55px rgba(15,49,74,.11)!important; backdrop-filter:blur(14px); }
    .candidate-auth-step { display:inline-flex; align-items:center; gap:7px; padding:7px 11px; border-radius:999px;
      color:#1769AA; background:#EAF4FF; border:1px solid #D6E9FC; font-size:.7rem; font-weight:800;
      letter-spacing:.08em; text-transform:uppercase; margin-bottom:24px; }
    .candidate-auth-step span { font-family:'Material Symbols Rounded'; font-size:16px; }
    .candidate-auth-form-title { color:#14213B; font-size:1.75rem; font-weight:850; letter-spacing:-.025em; margin-bottom:9px; }
    .candidate-auth-form-copy { color:#64748B; font-size:.9rem; line-height:1.6; margin-bottom:25px; }
    .candidate-auth-security { display:flex; align-items:flex-start; gap:10px; padding:12px 13px; border-radius:12px;
      color:#52627A; background:#F8FAFC; border:1px solid #E2E8F0; font-size:.76rem; line-height:1.45; margin:18px 0 13px; }
    .candidate-auth-security span { font-family:'Material Symbols Rounded'; color:#0F8A67; font-size:18px; }
    .st-key-candidate_auth_form .stTextInput input { min-height:49px; border-radius:12px!important; background:#F8FAFC!important;
      border:1px solid #D8E1EC!important; color:#17233C!important; }
    .st-key-candidate_auth_form .stTextInput input:focus { border-color:#2F80ED!important;
      box-shadow:0 0 0 3px rgba(47,128,237,.14)!important; }
    .st-key-candidate_auth_form label { color:#334155!important; font-weight:700!important; }
    .st-key-candidate_auth_form button { min-height:49px!important; border-radius:12px!important; font-weight:750!important; }
    .st-key-candidate_auth_form button[kind="primary"] { color:#fff!important; border:0!important;
      background:linear-gradient(135deg,#378ADD,#1565AD)!important; box-shadow:0 10px 22px rgba(21,101,173,.18)!important; }
    .st-key-candidate_auth_form button[kind="primary"]:hover { transform:translateY(-1px); box-shadow:0 13px 26px rgba(21,101,173,.25)!important; }
    .st-key-candidate_auth_form button[kind="secondary"] { color:#40516A!important; border-color:#D8E1EC!important; background:#fff!important; }
    .candidate-auth-divider { display:flex; align-items:center; gap:12px; color:#94A3B8; font-size:.7rem; margin:16px 0; }
    .candidate-auth-divider:before,.candidate-auth-divider:after { content:""; height:1px; background:#E2E8F0; flex:1; }
    .candidate-auth-help { color:#718096; text-align:center; font-size:.72rem; margin-top:17px; }
    @media(max-width:640px){
      .stMainBlockContainer{padding:1rem .85rem 2rem}.portal-hero{padding:25px 20px}.portal-brand img{width:104px}
      .st-key-candidate_auth_value,.st-key-candidate_auth_form{min-height:auto;padding:28px 23px!important;border-radius:21px!important}
      .candidate-auth-logo-wrap{margin-bottom:28px}.candidate-auth-copy{font-size:.91rem}.candidate-auth-heading{font-size:2rem}
      .application-card{grid-template-columns:52px minmax(0,1fr);padding:18px 16px}.application-company-logo{width:48px;height:48px}
      .application-status{grid-column:2;justify-self:start}.candidate-applications-head{display:block}
    }
    @media(prefers-reduced-motion:reduce){.st-key-candidate_auth_form button{transition:none!important;transform:none!important}}
    </style>
    """)


@st.cache_data(ttl=60, max_entries=4, show_spinner=False)
def _published_jobs() -> list[dict]:
    return db.fetch_published_jobs(limit=200)


def _logo_data_uri() -> str:
    path = os.path.join(os.path.dirname(__file__), "assets", "logo_header.png")
    try:
        with open(path, "rb") as logo:
            return "data:image/png;base64," + base64.b64encode(logo.read()).decode("ascii")
    except OSError:
        return ""


def _company_logo_data_uri(encoded_logo: str) -> str:
    if not encoded_logo:
        return ""
    try:
        raw = base64.b64decode(encoded_logo, validate=True)
    except Exception:
        return ""
    mime = "image/jpeg" if raw.startswith(b"\xff\xd8\xff") else "image/png"
    return f"data:{mime};base64,{encoded_logo}"


def _write_auth_cookies(access_token: str, refresh_token: str) -> None:
    """Persist only the Supabase browser session; never render token text."""
    script = f"""
    <script>
    document.cookie = {_ACCESS_COOKIE!r} + "=" + encodeURIComponent({json.dumps(access_token)}) + "; Max-Age={_COOKIE_MAX_AGE}; Path=/; Secure; SameSite=Lax";
    document.cookie = {_REFRESH_COOKIE!r} + "=" + encodeURIComponent({json.dumps(refresh_token)}) + "; Max-Age={_COOKIE_MAX_AGE}; Path=/; Secure; SameSite=Lax";
    </script>
    """
    st.html(script, unsafe_allow_javascript=True)


def _clear_auth_cookies() -> None:
    st.html(
        f'<script>document.cookie="{_ACCESS_COOKIE}=; Max-Age=0; Path=/; Secure; SameSite=Lax";'
        f'document.cookie="{_REFRESH_COOKIE}=; Max-Age=0; Path=/; Secure; SameSite=Lax";</script>',
        unsafe_allow_javascript=True,
    )


def _restore_candidate_session(client) -> None:
    access_token = unquote(st.context.cookies.get(_ACCESS_COOKIE, ""))
    refresh_token = unquote(st.context.cookies.get(_REFRESH_COOKIE, ""))
    if not access_token or not refresh_token:
        return
    try:
        response = client.auth.set_session(access_token, refresh_token)
        session = getattr(response, "session", None)
        if session and (session.access_token != access_token or session.refresh_token != refresh_token):
            _write_auth_cookies(session.access_token, session.refresh_token)
    except Exception:
        _clear_auth_cookies()


def _current_candidate() -> dict | None:
    client = db._get_client()
    if client is None:
        return None
    cached_user = st.session_state.get("candidate_user")
    try:
        user = client.auth.get_user().user
    except Exception:
        user = None
    # Session State can outlive the Supabase client's in-memory JWT after a
    # reconnect or server restart. Never trust the cached identity by itself:
    # restore the signed browser session before making an RLS-protected query.
    if not user or (cached_user and str(user.id) != str(cached_user.get("id"))):
        _restore_candidate_session(client)
        try:
            user = client.auth.get_user().user
        except Exception:
            user = None
    try:
        if not user or not getattr(user, "email", None):
            st.session_state.pop("candidate_user", None)
            return None
        current_user = {"id": user.id, "email": user.email}
        st.session_state.candidate_user = current_user
        return current_user
    except Exception:
        return None


def _sign_out() -> None:
    client = db._get_client()
    if client:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    _clear_auth_cookies()
    st.session_state.pop("candidate_email", None)
    st.session_state.pop("candidate_otp_sent", None)
    st.session_state.pop("candidate_user", None)
    st.session_state.pop("candidate_pending_tokens", None)


def _go_to_account_selection() -> None:
    st.session_state.show_account_gate = True
    st.session_state.pop("entry_role", None)
    st.query_params.clear()


def _go_to_application(job_id) -> None:
    st.query_params.clear()
    st.query_params["apply"] = str(job_id)


def _back_to_account_selection() -> None:
    st.session_state.pop("entry_role", None)
    st.query_params.clear()


def _auth_panel() -> dict | None:
    user = _current_candidate()
    if user:
        return user
    logo = _logo_data_uri()
    logo_html = (
        f'<div class="candidate-auth-logo-wrap"><img class="candidate-auth-logo" src="{logo}" alt="ICD Platform"></div>'
        if logo else '<div class="candidate-auth-logo-wrap"><strong>ICD Platform</strong></div>'
    )

    value_col, form_col = st.columns([1.08, .92], gap="large")
    with value_col:
        with st.container(height="stretch", key="candidate_auth_value"):
            st.html(
                f'{logo_html}'
                '<div class="candidate-auth-eyebrow">Candidate careers portal</div>'
                '<h1 class="candidate-auth-heading">Your next opportunity starts here.</h1>'
                '<p class="candidate-auth-copy">Discover verified roles from trusted hiring teams, apply securely, '
                'and follow every application from one simple workspace.</p>'
                '<div class="candidate-auth-benefits">'
                '<div class="candidate-auth-benefit"><span class="candidate-auth-benefit-icon">verified</span>Verified company openings</div>'
                '<div class="candidate-auth-benefit"><span class="candidate-auth-benefit-icon">person</span>One reusable candidate profile</div>'
                '<div class="candidate-auth-benefit"><span class="candidate-auth-benefit-icon">track_changes</span>Live application progress</div>'
                '</div>'
            )

    with form_col:
        with st.container(height="stretch", key="candidate_auth_form"):
            _otp_sent = bool(st.session_state.get("candidate_otp_sent"))
            _step_icon = "mark_email_read" if _otp_sent else "lock"
            _step_text = "Step 2 of 2 · Verify email" if _otp_sent else "Secure candidate access"
            _form_title = "Enter your verification code" if _otp_sent else "Sign in to continue"
            _form_copy = (
                "Use the numeric code from your email. It expires shortly for your security."
                if _otp_sent else
                "No password is needed. We will email you a secure one-time verification code."
            )
            st.html(
                f'<div class="candidate-auth-step"><span>{_step_icon}</span>{_step_text}</div>'
                f'<div class="candidate-auth-form-title">{_form_title}</div>'
                f'<div class="candidate-auth-form-copy">{_form_copy}</div>'
            )

            email = st.text_input(
                "Email address",
                value=st.session_state.get("candidate_email", ""),
                placeholder="you@example.com",
                disabled=_otp_sent,
                key="candidate_auth_email",
            ).strip().lower()

            if not _otp_sent:
                if st.button(
                    "Email verification code", type="primary", icon=":material/mail:",
                    width="stretch", key="candidate_auth_send_code",
                ):
                    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                        st.error("Enter a valid email address.")
                    else:
                        try:
                            db._get_client().auth.sign_in_with_otp({"email": email})
                            st.session_state.candidate_email = email
                            st.session_state.candidate_otp_sent = True
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not send the code. Confirm Email Auth is enabled in Supabase. ({exc})")
                st.html(
                    '<div class="candidate-auth-security"><span>shield_lock</span><div><strong>Password-free and secure.</strong><br>'
                    'Your verified session remains active on this device, so you do not need to sign in every visit.</div></div>'
                    '<div class="candidate-auth-divider">or</div>'
                )
                st.button(
                    "Back to account selection", icon=":material/arrow_back:",
                    width="stretch", key="candidate_auth_back",
                    on_click=_back_to_account_selection,
                )
                st.html('<div class="candidate-auth-help">We only use your email for secure access and application updates.</div>')
                return None

            st.caption(
                f"Code sent to **{st.session_state.get('candidate_email', email)}**. "
                "Check your inbox and spam folder."
            )
            code = st.text_input(
                "Verification code", max_chars=10, placeholder="Enter the code from your email",
                key=f"candidate_auth_code_{st.session_state.get('candidate_email', email)}",
            )
            if st.button(
                "Verify and continue", type="primary", icon=":material/arrow_forward:",
                width="stretch", key="candidate_auth_verify",
            ):
                if not code.strip().isdigit() or not 6 <= len(code.strip()) <= 10:
                    st.error("Enter the complete numeric verification code from your email.")
                    return None
                try:
                    response = db._get_client().auth.verify_otp({"email": st.session_state.get("candidate_email", email), "token": code.strip(), "type": "email"})
                    if getattr(response, "user", None):
                        session = getattr(response, "session", None)
                        current_user = {"id": response.user.id, "email": response.user.email}
                        if session:
                            st.session_state.candidate_pending_tokens = (
                                session.access_token,
                                session.refresh_token,
                            )
                        st.session_state.candidate_user = current_user
                        st.session_state.candidate_otp_sent = False
                        return current_user
                    st.error("That code could not be verified.")
                except Exception as exc:
                    st.error(f"Incorrect or expired code. ({exc})")
            if st.button(
                "Use another email", icon=":material/edit:", width="stretch", key="candidate_auth_change_email",
            ):
                st.session_state.candidate_otp_sent = False
                st.rerun()
    return None


def _ensure_profile(user: dict) -> dict | None:
    profile = db.fetch_candidate_profile(user["id"])
    if profile:
        return profile
    with st.form("candidate_profile_form", border=True):
        st.subheader("Complete your profile")
        st.caption("This information will be reused when you apply for a job.")
        full_name = st.text_input("Full name")
        st.text_input("Verified email address", value=user["email"], disabled=True)
        phone = st.text_input("Phone number (optional)", placeholder="+91 98765 43210")
        submitted = st.form_submit_button("Save profile", type="primary", icon=":material/save:")
    if submitted:
        if not full_name.strip():
            st.error("Enter your full name.")
        else:
            saved = db.save_candidate_profile({"user_id": user["id"], "full_name": full_name.strip(), "email": user["email"], "phone": phone.strip()})
            if saved:
                st.rerun()
            st.error(db.get_last_error() or "The profile could not be saved.")
    return None


def _job_card(job: dict, index: int) -> None:
    company = job.get("companies") or {}
    if not company and job.get("id"):
        public_job = db.fetch_public_job(job.get("id")) or {}
        company = public_job.get("companies") or {}
    title = html.escape(job.get("title") or "Open position")
    company_name = html.escape(company.get("name") or "Hiring organization")
    company_industry = html.escape(company.get("industry") or "Careers")
    logo_uri = _company_logo_data_uri(company.get("logo_base64") or "")
    company_initial = html.escape((company_name[:1] or "C").upper())
    company_logo = (
        f'<img class="job-logo" src="{logo_uri}" alt="{company_name} logo" '
        'style="width:48px;height:48px;object-fit:contain;padding:5px;display:block;">'
        if logo_uri else f'<span class="job-logo-fallback">{company_initial}</span>'
    )
    meta = " · ".join(filter(None, [job.get("location"), job.get("employment_type"), job.get("experience_level")])) or "Role details available"
    chips = "".join(f"<span>{html.escape(str(skill))}</span>" for skill in (job.get("required_skills") or [])[:5])
    st.html(f'<div class="job-card"><div class="job-brand">{company_logo}<div><div class="job-company">{company_name}</div><div class="job-industry">{company_industry}</div></div></div><div class="job-title">{title}</div><div class="job-meta">{html.escape(meta)}</div><div class="job-chips">{chips}</div></div>')
    st.button(
        "View and apply", key=f"candidate_apply_{job.get('id')}_{index}",
        type="primary", icon=":material/arrow_forward:", width="stretch",
        on_click=_go_to_application, args=(job["id"],),
    )


def _render_my_applications(user: dict) -> None:
    applications = db.fetch_candidate_applications(user["id"])
    st.html(
        '<section class="candidate-applications-head"><div>'
        f'<h2>My applications <span style="color:#1769AA">({len(applications)})</span></h2>'
        '<p>Track every application and see when a recruiter moves you to the next stage.</p>'
        '</div></section>'
    )
    if not applications:
        st.info("You have not applied for a published role yet.", icon=":material/inbox:")
        return
    status_icons = {
        "Submitted": "send", "Under Review": "visibility", "Shortlisted": "star",
        "Interview Scheduled": "event", "Selected": "check_circle", "Hired": "workspace_premium", "Rejected": "cancel",
    }
    for application in applications:
        job = application.get("jobs") or {}
        company = job.get("companies") or {}
        company_name = html.escape(company.get("name") or "Hiring organization")
        title = html.escape(job.get("title") or "Position")
        location = html.escape(job.get("location") or "Location not specified")
        applied = html.escape(str(application.get("applied_at") or "")[:10] or "Recently")
        resume = html.escape(application.get("resume_filename") or "Uploaded resume")
        status = html.escape(application.get("status") or "Submitted")
        logo_uri = _company_logo_data_uri(company.get("logo_base64") or "")
        logo = (
            f'<img src="{logo_uri}" alt="{company_name} logo">'
            if logo_uri else f'<span>{html.escape((company_name[:1] or "C").upper())}</span>'
        )
        icon = status_icons.get(application.get("status") or "Submitted", "schedule")
        st.html(
            '<article class="application-card">'
            f'<div class="application-company-logo">{logo}</div>'
            '<div><div class="application-company">' + company_name + '</div>'
            f'<div class="application-title">{title}</div>'
            '<div class="application-meta">'
            f'<span><i>location_on</i>{location}</span><span><i>calendar_today</i>Applied {applied}</span>'
            '</div>'
            f'<div class="application-resume"><strong>Resume:</strong> {resume}</div></div>'
            f'<div class="application-status"><i>{icon}</i>{status}</div>'
            '</article>'
        )


def render_candidate_portal() -> None:
    auth_slot = st.empty()
    with auth_slot.container():
        user = _auth_panel()
    if not user:
        return
    auth_slot.empty()
    pending_tokens = st.session_state.pop("candidate_pending_tokens", None)
    if pending_tokens:
        _write_auth_cookies(*pending_tokens)
    profile = _ensure_profile(user)
    if not profile:
        return
    logo = _logo_data_uri()
    logo_html = (
        f'<img src="{logo}" alt="ICD Platform" style="width:124px;max-height:48px;object-fit:contain;display:block;">'
        if logo else "ICD Platform"
    )
    st.html(f'<div class="portal-nav"><div class="portal-brand">{logo_html}</div><div class="portal-user"><span class="portal-user-dot"></span>{html.escape(profile.get("full_name") or user.get("email") or "Candidate")}</div></div>')
    st.button(
        "Back to account selection",
        icon=":material/arrow_back:",
        key="candidate_portal_account_selection",
        on_click=_go_to_account_selection,
    )
    st.html(f'<section class="portal-hero"><div class="portal-eyebrow">Welcome, {html.escape(profile.get("full_name") or "candidate")}</div><h1>Discover roles built for your skills</h1><p>Browse verified openings, apply securely with your resume, and follow every application from one place.</p></section>')
    jobs_tab, applications_tab = st.tabs(["Find jobs", "My applications"], on_change="rerun")
    if applications_tab.open:
        with applications_tab:
            _render_my_applications(user)
        return
    with jobs_tab:
        search = st.text_input("Search jobs", placeholder="Search by role, skill, department or location", icon=":material/search:")
    jobs = _published_jobs()
    if search.strip():
        needle = search.strip().lower()
        jobs = [job for job in jobs if needle in " ".join(str(job.get(k) or "") for k in ("title", "department", "location", "description", "required_skills")).lower()]
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        st.subheader(f"Open positions ({len(jobs)})")
        if st.button("Sign out", icon=":material/logout:"):
            _sign_out()
            st.rerun()
    if not jobs:
        st.info("No published jobs match your search.", icon=":material/search_off:")
        return
    for start in range(0, len(jobs), 3):
        columns = st.columns(3)
        for offset, job in enumerate(jobs[start:start + 3]):
            with columns[offset]:
                _job_card(job, start + offset)
