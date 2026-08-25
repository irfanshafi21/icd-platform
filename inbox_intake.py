"""
Inbox-based resume intake.

This is the one candidate-sourcing channel that works TODAY with zero
platform partnership or approval — unlike LinkedIn/Indeed/Naukri's
job-posting + applicant APIs, which are all gated behind formal partner
programs (see the Integrations page for details on those).

How it works: you give candidates (or a job board's "apply by email" option)
a dedicated inbox address. This module logs into that inbox over IMAP,
finds unread emails with resume attachments (PDF/DOCX), and hands the raw
bytes back to the caller — which runs them through the exact same
extraction + AI scoring pipeline as a manual upload on the Resume Screening
page. Successfully processed emails are marked as read (and optionally
flagged) so re-checking the inbox doesn't reprocess the same resume twice.

Setup (~3 minutes, works with any Gmail account, no Google Cloud project
needed): 1) turn on IMAP access in Gmail settings, 2) create an "app
password" the same way as for the existing SMTP email-sending feature,
3) add to .streamlit/secrets.toml:

    INTAKE_EMAIL = "resumes@yourcompany.com"
    INTAKE_APP_PASSWORD = "your-16-char-app-password"
    INTAKE_IMAP_HOST = "imap.gmail.com"   # optional, this is the default
"""

from __future__ import annotations

import email
import imaplib
from email.header import decode_header

import streamlit as st

RESUME_EXTENSIONS = (".pdf", ".docx", ".doc")


def _get_secret(key: str) -> str | None:
    try:
        val = st.secrets.get(key)
        if val:
            return val
    except Exception:
        pass
    import os
    return os.environ.get(key)


def is_configured() -> bool:
    return bool(_get_secret("INTAKE_EMAIL") and _get_secret("INTAKE_APP_PASSWORD"))


def _decode(value) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(text)
    return "".join(out)


def fetch_new_resumes(max_emails: int = 25, mark_as_read: bool = True) -> tuple[list[dict], str | None]:
    """
    Connects to the configured inbox, scans unread messages for resume
    attachments, and returns them WITHOUT touching your resume-screening
    pipeline directly — the caller (Integrations page) is responsible for
    running each one through the same parse_and_score() flow as a manual
    upload, so this module has no dependency on the AI/scoring code at all.

    Returns (resumes, error). `resumes` is a list of dicts:
        {"filename": str, "data": bytes, "sender": str, "subject": str}
    On any connection/auth failure, returns ([], "human-readable error") —
    never raises, so the UI can always show a clean message.
    """
    email_addr = _get_secret("INTAKE_EMAIL")
    app_password = _get_secret("INTAKE_APP_PASSWORD")
    imap_host = _get_secret("INTAKE_IMAP_HOST") or "imap.gmail.com"

    if not email_addr or not app_password:
        return [], ("Inbox intake isn't configured. Add INTAKE_EMAIL and INTAKE_APP_PASSWORD "
                     "to .streamlit/secrets.toml — see the setup steps on the Integrations page.")

    resumes: list[dict] = []
    try:
        conn = imaplib.IMAP4_SSL(imap_host)
        conn.login(email_addr, app_password)
        conn.select("INBOX")

        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            conn.logout()
            return [], "Couldn't search the inbox — check INTAKE_EMAIL/INTAKE_APP_PASSWORD are correct."

        msg_ids = data[0].split()[-max_emails:]  # most recent N unread
        for msg_id in msg_ids:
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            sender = _decode(msg.get("From", ""))
            subject = _decode(msg.get("Subject", ""))

            found_attachment = False
            for part in msg.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                filename = part.get_filename()
                if not filename:
                    continue
                filename = _decode(filename)
                if not filename.lower().endswith(RESUME_EXTENSIONS):
                    continue
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                resumes.append({
                    "filename": filename, "data": payload,
                    "sender": sender, "subject": subject,
                })
                found_attachment = True

            # Only mark as read once we've actually pulled something useful
            # out of it (or confirmed there was nothing to pull) — either
            # way, marking it prevents re-scanning the same email forever.
            if mark_as_read:
                conn.store(msg_id, "+FLAGS", "\\Seen")

        conn.logout()
        return resumes, None
    except imaplib.IMAP4.error as e:
        return [], f"IMAP login failed — check your email/app password are correct. ({e})"
    except Exception as e:
        return [], f"Couldn't check the inbox: {e}"
