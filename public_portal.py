"""
Public candidate-facing pages — reachable via a plain link or QR code, no
login required. Two pages, both routed through query params on app.py:

  ?apply=<job_id>   -> single-job application form (resume + contact info)
  ?portal=1         -> "check my applications" page (email + OTP, then shows
                       every job applied to across companies, and status)

Kept in its own module so the public surface area is easy to audit — this is
the one part of the app a stranger on the internet can reach without logging
in, so it should touch as little of the rest of the app as possible.
"""

import base64
import html
import os
import random
import time
import streamlit as st

import auth
import db
import email_utils


# ----------------------------- SHARED HELPERS -----------------------------

def _public_page_styles() -> None:
    """Mobile-first styling for candidate-facing pages only."""
    st.html("""
    <style>
    [data-testid="stHeader"], [data-testid="stToolbar"], footer { display: none !important; }
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 8% 0%, rgba(37,99,235,.10), transparent 30%),
            radial-gradient(circle at 92% 12%, rgba(8,145,178,.09), transparent 25%),
            #F5F8FC;
    }
    .stMainBlockContainer { max-width: 760px; padding-top: 2rem; padding-bottom: 3rem; }
    .apply-brand {
        display:flex; align-items:center; gap:14px; margin-bottom:18px;
        padding:14px 18px; background:rgba(255,255,255,.92);
        border:1px solid #DCE6F1; border-radius:18px;
        box-shadow:0 8px 28px rgba(15,49,74,.08);
    }
    .apply-logo {
        width:54px; height:54px; flex:0 0 54px; border-radius:14px;
        display:flex; align-items:center; justify-content:center; overflow:hidden;
        background:#EFF6FF; border:1px solid #DBEAFE;
        color:#1D4ED8; font-size:1.15rem; font-weight:800;
    }
    .apply-logo img { width:100%; height:100%; object-fit:contain; padding:5px; }
    .apply-company { color:#102A43; font-size:1.05rem; font-weight:800; line-height:1.25; }
    .apply-brand-copy { color:#64748B; font-size:.8rem; margin-top:3px; }
    .apply-hero {
        position:relative; overflow:hidden; padding:28px;
        color:#FFFFFF; border-radius:22px;
        background:linear-gradient(135deg,#12314A 0%,#185FA5 58%,#0891B2 100%);
        box-shadow:0 16px 38px rgba(18,49,74,.18); margin-bottom:20px;
    }
    .apply-hero:after {
        content:""; position:absolute; width:190px; height:190px; right:-65px; top:-95px;
        border-radius:50%; border:34px solid rgba(255,255,255,.08);
    }
    .apply-eyebrow { font-size:.72rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; opacity:.82; }
    .apply-title { font-size:clamp(1.65rem,6vw,2.35rem); font-weight:850; line-height:1.15; margin:9px 0 10px; }
    .apply-subtitle { max-width:560px; font-size:.92rem; line-height:1.55; opacity:.88; }
    .apply-meta { display:flex; gap:9px; flex-wrap:wrap; margin-top:18px; }
    .apply-meta span { padding:6px 10px; border-radius:999px; background:rgba(255,255,255,.14); font-size:.76rem; font-weight:700; }
    .role-section { margin:18px 0; padding:22px; border:1px solid #DCE6F1; border-radius:18px; background:#FFFFFF; box-shadow:0 8px 24px rgba(15,49,74,.05); }
    .role-section-title { display:flex; align-items:center; gap:9px; color:#102A43; font-size:1.02rem; font-weight:850; margin-bottom:10px; }
    .role-copy { color:#475569; font-size:.9rem; line-height:1.7; white-space:pre-line; }
    .role-skills { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
    .role-skills span { padding:7px 11px; border-radius:999px; color:#185FA5; background:#EAF3FF; border:1px solid #D7E9FF; font-size:.76rem; font-weight:800; }
    [data-testid="stForm"] {
        background:#FFFFFF; border:1px solid #DCE6F1 !important; border-radius:22px !important;
        padding:24px !important; box-shadow:0 12px 32px rgba(15,49,74,.08);
    }
    [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
        min-height:50px; border-radius:12px; font-weight:800; letter-spacing:.01em;
        box-shadow:0 8px 18px rgba(37,99,235,.20);
    }
    .apply-form-heading { color:#102A43; font-size:1.12rem; font-weight:800; margin-bottom:-4px; }
    .apply-form-note { color:#64748B; font-size:.8rem; margin-bottom:10px; }
    .apply-success {
        text-align:center; padding:32px 24px; background:#F0FDF4;
        border:1px solid #BBF7D0; border-radius:22px; box-shadow:0 10px 28px rgba(22,163,74,.08);
    }
    .apply-success-icon { width:58px; height:58px; margin:0 auto 14px; border-radius:50%; display:flex;
        align-items:center; justify-content:center; background:#16A34A; color:#FFFFFF; font-size:1.8rem; font-weight:800; }
    .apply-success-title { color:#14532D; font-size:1.3rem; font-weight:850; }
    .apply-success-copy { color:#3F6650; font-size:.88rem; line-height:1.55; margin-top:7px; }
    @media (max-width: 640px) {
        .stMainBlockContainer { padding:1rem .85rem 2rem; }
        .apply-brand { border-radius:15px; padding:11px 13px; }
        .apply-logo { width:46px; height:46px; flex-basis:46px; border-radius:12px; }
        .apply-hero { padding:23px 19px; border-radius:18px; }
        [data-testid="stForm"] { padding:18px !important; border-radius:18px !important; }
    }
    </style>
    """)


def _logo_data_uri(encoded_logo: str) -> str:
    """Return a validated logo data URI, or an empty string."""
    if not encoded_logo:
        return ""
    try:
        raw = base64.b64decode(encoded_logo, validate=True)
    except Exception:
        return ""
    mime = "image/jpeg" if raw.startswith(b"\xff\xd8\xff") else "image/png"
    return f"data:{mime};base64,{encoded_logo}"


def _company_brand(job: dict) -> dict:
    company = job.get("companies") or auth.get_company_by_id(job.get("company_id")) or {}
    if company:
        return company
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "logo_header.png")
    fallback_logo = ""
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as logo_file:
            fallback_logo = base64.b64encode(logo_file.read()).decode("ascii")
    return {"name": "ICD Platform", "industry": "Intelligent Candidate Discovery", "logo_base64": fallback_logo}


def _render_apply_header(job: dict) -> None:
    company = _company_brand(job)
    company_name = html.escape(company.get("name") or "Hiring team")
    industry = html.escape(company.get("industry") or "Careers")
    logo_uri = _logo_data_uri(company.get("logo_base64") or "")
    initial = html.escape((company_name[:1] or "C").upper())
    logo_html = f'<img src="{logo_uri}" alt="{company_name} logo">' if logo_uri else initial
    title = html.escape(job.get("title") or "Open position")
    deadline = str(job.get("deadline") or "")[:10]
    meta_values = [job.get("location"), job.get("employment_type"), job.get("experience_level"), job.get("salary_range")]
    role_meta = "".join(f"<span>{html.escape(str(value))}</span>" for value in meta_values if value)
    deadline_html = f"<span>Apply by {html.escape(deadline)}</span>" if deadline else ""
    st.html(f"""
    <div class="apply-brand">
        <div class="apply-logo">{logo_html}</div>
        <div><div class="apply-company">{company_name}</div><div class="apply-brand-copy">{industry} · Careers</div></div>
    </div>
    <section class="apply-hero">
        <div class="apply-eyebrow">Now hiring</div>
        <div class="apply-title">{title}</div>
        <div class="apply-subtitle">Share your details and resume securely. The hiring team will review your application and contact you about the next step.</div>
        <div class="apply-meta">{role_meta}<span>Secure application</span><span>PDF or DOCX</span>{deadline_html}</div>
    </section>
    """)


def _render_job_details(job: dict) -> None:
    description = (job.get("description") or "").strip()
    responsibilities = (job.get("responsibilities") or "").strip()
    benefits = (job.get("benefits") or "").strip()
    skills = job.get("required_skills") or []
    if isinstance(skills, str):
        skills = [skill.strip() for skill in skills.split(",") if skill.strip()]

    if description:
        st.html(f'<section class="role-section"><div class="role-section-title">About this role</div><div class="role-copy">{html.escape(description)}</div></section>')

    left, right = st.columns(2)
    if responsibilities:
        with left.container(border=True, height="stretch"):
            st.subheader("What you will do", anchor=False)
            st.write(responsibilities)
    if benefits:
        with right.container(border=True, height="stretch"):
            st.subheader("What we offer", anchor=False)
            st.write(benefits)

    if skills:
        chips = "".join(f"<span>{html.escape(str(skill))}</span>" for skill in skills)
        st.html(f'<section class="role-section"><div class="role-section-title">Skills and qualifications</div><div class="role-skills">{chips}</div></section>')

def _otp_key(email: str) -> str:
    return f"portal_otp_{email.strip().lower()}"


def _generate_and_send_otp(email: str) -> tuple[bool, str]:
    """Generates a 6-digit code, stores it (with a 10-minute expiry) in this
    visitor's own session_state — fine here because the whole OTP exchange
    happens within one browser session/tab, unlike the screening thread-pool
    issue discussed earlier. Returns (sent_ok, message)."""
    code = f"{random.randint(0, 999999):06d}"
    st.session_state[_otp_key(email)] = {"code": code, "expires_at": time.time() + 600, "verified": False}
    if not email_utils.is_configured():
        # No email provider configured — surface the code directly so the
        # feature is still testable/usable in a dev environment.
        return True, f"Email isn't configured on this deployment. Your verification code is: {code}"
    ok, msg = email_utils.send_plain_email(
        to_email=email,
        subject="Your verification code",
        body_text=(
            f"Your verification code is: {code}\n\n"
            "It expires in 10 minutes. If you didn't request this, you can ignore this email."
        ),
        badge_text="VERIFICATION CODE",
    )
    if ok:
        return True, f"Code sent to {email}."
    return False, f"Couldn't send the code: {msg}"


def _verify_otp(email: str, entered_code: str) -> tuple[bool, str]:
    record = st.session_state.get(_otp_key(email))
    if not record:
        return False, "No code was requested for this email — request one first."
    if time.time() > record["expires_at"]:
        return False, "That code expired. Request a new one."
    if entered_code.strip() != record["code"]:
        return False, "Incorrect code — check and try again."
    record["verified"] = True
    return True, "Verified."


def _is_verified(email: str) -> bool:
    record = st.session_state.get(_otp_key(email))
    return bool(record and record.get("verified"))


# ----------------------------- APPLY PAGE -----------------------------

def render_apply_page(job_id: str):
    st.set_page_config(page_title="Apply for a role", page_icon=":material/work:", layout="centered")
    _public_page_styles()

    job = db.fetch_public_job(job_id)

    if not job:
        st.error("This job posting couldn't be found — the link may be outdated or the job was removed.")
        return

    if job.get("status") == "archived":
        st.warning("This job is no longer accepting applications.")
        return

    deadline = job.get("deadline")
    if deadline:
        from datetime import date
        try:
            deadline_date = date.fromisoformat(str(deadline)[:10])
            if deadline_date < date.today():
                st.warning(f"The application deadline for this role ({deadline_date.strftime('%d %b %Y')}) has passed.")
                return
        except Exception:
            pass

    if st.button("Back to all jobs", icon=":material/arrow_back:"):
        st.query_params.clear()
        st.query_params["candidate"] = "1"
        st.rerun()

    _render_apply_header(job)
    submitted_key = f"public_application_submitted_{job_id}"
    if st.session_state.get(submitted_key):
        st.html("""
        <div class="apply-success">
            <div class="apply-success-icon">✓</div>
            <div class="apply-success-title">Application received</div>
            <div class="apply-success-copy">Your resume and contact details were submitted successfully. Use the same email address on the <b>check my applications</b> page to follow your status.</div>
        </div>
        """)
        return

    _render_job_details(job)

    candidate_profile = None
    try:
        current_user = db._get_client().auth.get_user().user
        if current_user:
            candidate_profile = db.fetch_candidate_profile(current_user.id)
    except Exception:
        pass

    with st.form("public_apply_form", clear_on_submit=False):
        st.html('<div class="apply-form-heading">Your application</div><div class="apply-form-note">Fields marked with * are required. Your resume is shared only with the hiring organization.</div>')
        name = st.text_input("Full name *", value=(candidate_profile or {}).get("full_name", ""))
        email = st.text_input("Email *", value=(candidate_profile or {}).get("email", ""))
        phone = st.text_input("Phone number", value=(candidate_profile or {}).get("phone", ""))
        resume_file = st.file_uploader("Resume (PDF or DOCX) *", type=["pdf", "docx"])
        submitted = st.form_submit_button("Submit application", type="primary", width="stretch", icon=":material/send:")

    if submitted:
        if not name.strip() or not email.strip() or not resume_file:
            st.error("Name, email, and a resume file are all required.")
            return
        if "@" not in email or "." not in email.split("@")[-1]:
            st.error("Enter a valid email address.")
            return

        resume_bytes = resume_file.read()
        resume_b64 = base64.b64encode(resume_bytes).decode("utf-8")

        saved = db.save_public_application({
            "job_id": job.get("id"),
            "applicant_name": name.strip(),
            "applicant_email": email.strip().lower(),
            "applicant_phone": phone.strip(),
            "resume_filename": resume_file.name,
            "resume_base64": resume_b64,
        })

        if saved:
            st.session_state[submitted_key] = True
            st.rerun()
        else:
            st.error(
                f"Something went wrong saving your application ({db.get_last_error() or 'unknown error'}). "
                "Please try again in a moment."
            )


# ----------------------------- STATUS PAGE -----------------------------

def render_status_page():
    st.set_page_config(page_title="My Applications", page_icon="📋", layout="centered")
    st.markdown("## Check your application status")
    st.caption("Verify your email to see every job you've applied to and its current status.")

    email = st.text_input("Email address")

    if not email.strip():
        return

    email = email.strip().lower()

    if not _is_verified(email):
        col1, col2 = st.columns([2, 1])
        with col1:
            code = st.text_input("Verification code", key="portal_otp_input", max_chars=6)
        with col2:
            st.write("")
            st.write("")
            if st.button("Send code", width="stretch"):
                ok, msg = _generate_and_send_otp(email)
                (st.success if ok else st.error)(msg)
        if code:
            ok, msg = _verify_otp(email, code)
            if ok:
                st.rerun()
            else:
                st.error(msg)
        return

    # Verified — show every application for this email.
    st.success(f"Verified as {email}")
    applications = db.fetch_applications_by_email(email)

    if not applications:
        st.info("No applications found for this email yet.")
        return

    st.markdown(f"### {len(applications)} application(s)")
    for app_row in applications:
        job_info = app_row.get("jobs") or {}
        job_title = job_info.get("title", "Unknown role")
        status = app_row.get("status", "Submitted")
        applied_at = str(app_row.get("applied_at", ""))[:10]

        status_color = {
            "Submitted": "🔵", "Under Review": "🟡", "Shortlisted": "🟢",
            "Rejected": "🔴", "Interview Scheduled": "🟣", "Hired": "✅",
        }.get(status, "⚪")

        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{job_title}**")
                st.caption(f"Applied {applied_at}")
            with c2:
                st.markdown(f"{status_color} {status}")
