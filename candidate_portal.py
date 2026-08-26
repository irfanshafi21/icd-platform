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
    [data-testid="stAppViewContainer"] { background:#F5F8FC; }
    .stMainBlockContainer { max-width:1180px; padding-top:1.5rem; padding-bottom:3rem; }
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
    .job-company { color:#185FA5; font-size:.78rem; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }
    .job-title { color:#102A43; font-size:1.2rem; font-weight:850; margin:7px 0 9px; }
    .job-meta { color:#64748B; font-size:.82rem; line-height:1.5; min-height:40px; }
    .job-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:14px; min-height:31px; }
    .job-chips span { color:#0C4A6E; background:#E0F2FE; padding:5px 9px; border-radius:999px; font-size:.7rem; font-weight:750; }
    .auth-panel { max-width:720px; margin:2rem auto 1rem; padding:34px; background:linear-gradient(145deg,#FFFFFF,#F6FAFF);
      border:1px solid #DCE6F1; border-top:5px solid #2F80ED; border-radius:24px; box-shadow:0 18px 46px rgba(15,49,74,.11); }
    .auth-logo { width:145px; margin-bottom:24px; }
    .auth-points { display:flex; flex-wrap:wrap; gap:8px; margin-top:20px; }
    .auth-points span { padding:7px 11px; border-radius:999px; color:#185FA5; background:#EAF3FF; font-size:.75rem; font-weight:750; }
    @media(max-width:640px){.stMainBlockContainer{padding:1rem .85rem 2rem}.portal-hero{padding:25px 20px}.portal-brand img{width:104px}}
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
    try:
        user = client.auth.get_user().user
    except Exception:
        user = None
    if not user:
        _restore_candidate_session(client)
        try:
            user = client.auth.get_user().user
        except Exception:
            user = None
    try:
        if not user or not getattr(user, "email", None):
            return None
        return {"id": user.id, "email": user.email}
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


def _auth_panel() -> dict | None:
    user = _current_candidate()
    if user:
        return user
    logo = _logo_data_uri()
    logo_html = f'<img class="auth-logo" src="{logo}" alt="ICD Platform">' if logo else '<strong>ICD Platform</strong>'
    st.html(f'<div class="auth-panel">{logo_html}<div class="portal-eyebrow" style="color:#185FA5">Candidate access</div><h2>Find your next opportunity</h2><p style="color:#64748B">Sign in once with your email verification code. Your secure session stays active on this device.</p><div class="auth-points"><span>Verified openings</span><span>One-click profile</span><span>Live application status</span></div></div>')
    email = st.text_input("Email address", value=st.session_state.get("candidate_email", ""), placeholder="you@example.com").strip().lower()
    if not st.session_state.get("candidate_otp_sent"):
        if st.button("Email verification code", type="primary", icon=":material/mail:", width="stretch"):
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
        if st.button("Back to account selection", icon=":material/arrow_back:", width="stretch"):
            st.query_params.clear()
            st.session_state.pop("entry_role", None)
            st.rerun()
        return None
    st.caption(f"A verification code was sent to {st.session_state.get('candidate_email', email)}. Check your inbox and spam folder.")
    code = st.text_input("Verification code", max_chars=10, placeholder="Enter the code from your email")
    left, right = st.columns(2)
    if left.button("Verify and continue", type="primary", width="stretch"):
        if not code.strip().isdigit() or not 6 <= len(code.strip()) <= 10:
            st.error("Enter the complete numeric verification code from your email.")
            return None
        try:
            response = db._get_client().auth.verify_otp({"email": st.session_state.get("candidate_email", email), "token": code.strip(), "type": "email"})
            if getattr(response, "user", None):
                session = getattr(response, "session", None)
                if session:
                    _write_auth_cookies(session.access_token, session.refresh_token)
                st.session_state.candidate_otp_sent = False
                return {"id": response.user.id, "email": response.user.email}
            st.error("That code could not be verified.")
        except Exception as exc:
            st.error(f"Incorrect or expired code. ({exc})")
    if right.button("Use another email", width="stretch"):
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
    title = html.escape(job.get("title") or "Open position")
    company_name = html.escape(company.get("name") or "Hiring organization")
    logo_uri = _company_logo_data_uri(company.get("logo_base64") or "")
    company_initial = html.escape((company_name[:1] or "C").upper())
    company_logo = f'<img src="{logo_uri}" alt="{company_name} logo" style="width:38px;height:38px;object-fit:contain;border-radius:9px;background:#fff;padding:3px;border:1px solid #DBEAFE">' if logo_uri else f'<span style="width:38px;height:38px;border-radius:9px;background:#EAF3FF;color:#185FA5;display:inline-flex;align-items:center;justify-content:center;font-weight:850">{company_initial}</span>'
    meta = " · ".join(filter(None, [job.get("location"), job.get("employment_type"), job.get("experience_level")])) or "Role details available"
    chips = "".join(f"<span>{html.escape(str(skill))}</span>" for skill in (job.get("required_skills") or [])[:5])
    st.html(f'<div class="job-card"><div style="display:flex;align-items:center;gap:10px">{company_logo}<div class="job-company">{company_name}</div></div><div class="job-title">{title}</div><div class="job-meta">{html.escape(meta)}</div><div class="job-chips">{chips}</div></div>')
    if st.button("View and apply", key=f"candidate_apply_{job.get('id')}_{index}", type="primary", icon=":material/arrow_forward:", width="stretch"):
        st.query_params.clear()
        st.query_params["apply"] = str(job["id"])
        st.rerun()


def _render_my_applications(user: dict) -> None:
    applications = db.fetch_candidate_applications(user["id"])
    st.subheader(f"My applications ({len(applications)})")
    st.caption("Your status updates automatically when the recruiter moves your application forward.")
    if not applications:
        st.info("You have not applied for a published role yet.", icon=":material/inbox:")
        return
    status_colors = {
        "Submitted": "blue", "Under Review": "orange", "Shortlisted": "green",
        "Interview Scheduled": "violet", "Selected": "green", "Hired": "green", "Rejected": "red",
    }
    for application in applications:
        job = application.get("jobs") or {}
        company = job.get("companies") or {}
        with st.container(border=True):
            header, badge = st.columns([4, 1], vertical_alignment="center")
            with header:
                st.markdown(f"#### {job.get('title') or 'Position'}")
                st.caption(" · ".join(filter(None, [company.get("name"), job.get("location"), str(application.get("applied_at") or "")[:10]])))
            with badge:
                status = application.get("status") or "Submitted"
                st.badge(status, color=status_colors.get(status, "gray"))
            st.caption(f"Resume: {application.get('resume_filename') or 'Uploaded resume'}")


def render_candidate_portal() -> None:
    st.set_page_config(page_title="ICD candidate portal", page_icon=":material/work:", layout="wide", initial_sidebar_state="collapsed")
    _styles()
    user = _auth_panel()
    if not user:
        return
    profile = _ensure_profile(user)
    if not profile:
        return
    logo = _logo_data_uri()
    logo_html = f'<img src="{logo}" alt="ICD Platform">' if logo else "ICD Platform"
    st.html(f'<div class="portal-nav"><div class="portal-brand">{logo_html}</div><div class="portal-user"><span class="portal-user-dot"></span>{html.escape(profile.get("full_name") or user.get("email") or "Candidate")}</div></div>')
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
