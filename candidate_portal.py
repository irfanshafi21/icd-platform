"""Fast candidate-facing portal with passwordless email OTP authentication."""

from __future__ import annotations

import base64
import html
import os
import streamlit as st

import db


def _styles() -> None:
    st.html("""
    <style>
    [data-testid="stHeader"], [data-testid="stToolbar"], footer { display:none!important; }
    [data-testid="stAppViewContainer"] { background:#F5F8FC; }
    .stMainBlockContainer { max-width:1180px; padding-top:1.5rem; padding-bottom:3rem; }
    .portal-nav { display:flex; align-items:center; justify-content:space-between; gap:18px; padding:13px 18px;
      border:1px solid #DCE6F1; border-radius:18px; background:#fff; box-shadow:0 8px 26px rgba(15,49,74,.07); margin-bottom:22px; }
    .portal-brand img { width:124px; max-height:48px; object-fit:contain; }
    .portal-hero { padding:34px; border-radius:24px; color:#fff; overflow:hidden; position:relative;
      background:linear-gradient(135deg,#0B2A52 0%,#185FA5 58%,#0891B2 100%);
      box-shadow:0 16px 38px rgba(18,49,74,.16); margin-bottom:24px; }
    .portal-hero h1 { margin:0 0 8px; font-size:clamp(1.8rem,4vw,2.7rem); line-height:1.12; }
    .portal-hero p { margin:0; max-width:680px; opacity:.88; line-height:1.55; }
    .portal-eyebrow { font-size:.72rem; text-transform:uppercase; letter-spacing:.14em; font-weight:850; opacity:.8; }
    .job-card { min-height:190px; padding:22px; border:1px solid #DCE6F1; border-radius:18px;
      background:#fff; box-shadow:0 8px 24px rgba(15,49,74,.06); }
    .job-company { color:#185FA5; font-size:.78rem; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }
    .job-title { color:#102A43; font-size:1.2rem; font-weight:850; margin:7px 0 9px; }
    .job-meta { color:#64748B; font-size:.82rem; line-height:1.5; min-height:40px; }
    .job-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:14px; min-height:31px; }
    .job-chips span { color:#0C4A6E; background:#E0F2FE; padding:5px 9px; border-radius:999px; font-size:.7rem; font-weight:750; }
    .auth-panel { max-width:560px; margin:3rem auto 1rem; padding:28px; background:#fff; border:1px solid #DCE6F1;
      border-radius:22px; box-shadow:0 16px 40px rgba(15,49,74,.10); }
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


def _current_candidate() -> dict | None:
    client = db._get_client()
    if client is None:
        return None
    try:
        user = client.auth.get_user().user
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
    st.session_state.pop("candidate_email", None)
    st.session_state.pop("candidate_otp_sent", None)


def _auth_panel() -> dict | None:
    user = _current_candidate()
    if user:
        return user
    st.html('<div class="auth-panel"><div class="portal-eyebrow" style="color:#185FA5">Candidate access</div><h2>Find your next opportunity</h2><p style="color:#64748B">Enter your email address. We will send a secure six-digit verification code.</p></div>')
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
    st.caption(f"A six-digit code was sent to {st.session_state.get('candidate_email', email)}. Check your inbox and spam folder.")
    code = st.text_input("Verification code", max_chars=6, placeholder="000000")
    left, right = st.columns(2)
    if left.button("Verify and continue", type="primary", width="stretch"):
        try:
            response = db._get_client().auth.verify_otp({"email": st.session_state.get("candidate_email", email), "token": code.strip(), "type": "email"})
            if getattr(response, "user", None):
                st.session_state.candidate_otp_sent = False
                st.rerun()
            st.error("That code could not be verified.")
        except Exception as exc:
            st.error(f"Incorrect or expired code. ({exc})")
    if right.button("Use another number", width="stretch"):
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
    meta = " · ".join(filter(None, [job.get("location"), job.get("employment_type"), job.get("experience_level")])) or "Role details available"
    chips = "".join(f"<span>{html.escape(str(skill))}</span>" for skill in (job.get("required_skills") or [])[:5])
    st.html(f'<div class="job-card"><div class="job-company">{company_name}</div><div class="job-title">{title}</div><div class="job-meta">{html.escape(meta)}</div><div class="job-chips">{chips}</div></div>')
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
    st.html(f'<div class="portal-nav"><div class="portal-brand">{logo_html}</div><div>Candidate portal</div></div>')
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
