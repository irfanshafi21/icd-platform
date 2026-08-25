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
import random
import time
import streamlit as st

import db
import email_utils


# ----------------------------- SHARED HELPERS -----------------------------

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
    st.set_page_config(page_title="Apply", page_icon="📝", layout="centered")
    st.markdown("## Apply for this role")

    jobs = db.fetch_jobs(include_archived=True)
    job = next((j for j in jobs if str(j.get("id")) == str(job_id)), None)

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

    st.markdown(f"### {job.get('title', 'Untitled Role')}")
    if job.get("description"):
        with st.expander("Job description", expanded=True):
            st.write(job["description"])
    if deadline:
        st.caption(f"📅 Apply by {str(deadline)[:10]}")

    st.divider()

    with st.form("public_apply_form", clear_on_submit=False):
        name = st.text_input("Full name *")
        email = st.text_input("Email *")
        phone = st.text_input("Phone number")
        resume_file = st.file_uploader("Resume (PDF or DOCX) *", type=["pdf", "docx"])
        submitted = st.form_submit_button("Submit Application", type="primary", width="stretch")

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
            st.success(
                "Application submitted! You can check its status anytime using the "
                "**check my applications** page with this same email."
            )
            st.balloons()
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
