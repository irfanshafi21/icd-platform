"""
Local settings persistence — stores non-sensitive UI preferences (default
theme, notification toggles) in a small JSON file next to the app, so they
survive app restarts on the same machine without needing a database.

Deliberately does NOT store API keys or secrets here — those stay in
st.secrets/.streamlit/secrets.toml (or a session-only override), never
written to this file.
"""

import json
import os

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".local_settings.json")

DEFAULTS = {
    "default_theme": "light",   # "light" | "dark"
    "show_success_toasts": True,
    "offer_company_name": "",
    "offer_company_phone": "",
    "offer_company_email": "",
    "offer_hr_name": "",
    "offer_hr_title": "HR Manager",
    "offer_logo_path": "",       # path to an uploaded company logo, if any
    "offer_signature_style": "Elegant Script",
    "sender_email": "",  # overrides the "From" address for outgoing mail (offer letters, interview invites)
    "interview_email_subject_template": "Your {interview_type} Interview with {company_name} — {when}",
    "interview_email_body_template": (
        "Hi {first_name},\n\n"
        "Congratulations — after reviewing your application{job_role_suffix}, we'd like to "
        "invite you to the next step in our hiring process: a {interview_type} interview "
        "with {company_name}.\n\n"
        "Here are the details:\n\n"
        "Interview type: {interview_type}\n"
        "Date & time: {when}\n"
        "Mode: {mode}\n"
        "{link_or_location}"
        "{notes_line}\n"
        "A few things to help you prepare: please join a few minutes early to account for "
        "any last-minute technical setup, have a copy of your resume handy for reference, "
        "and come ready to walk us through your relevant experience and ask any questions "
        "you have about the role or team. If anything above needs to be rescheduled, just "
        "reply to this email and we'll find a time that works better.\n\n"
        "We're genuinely looking forward to speaking with you and learning more about your "
        "background.\n\n"
        "Best regards,\n{company_name}\nHiring Team\n"
    ),
    "rejection_email_subject_template": "Update on your application{job_role_suffix}",
    "rejection_email_body_template": (
        "Hi {first_name},\n\n"
        "Thank you for applying{job_role_suffix} and for taking the time to share your background, "
        "experience, and the work you've done — we know putting an application together takes real effort, "
        "and we don't take that lightly.\n\n"
        "Our team carefully reviewed your profile alongside the requirements for {job_role} and compared "
        "it against the rest of the applicant pool. After that review, we've decided to move forward with "
        "other candidates whose current experience more closely matches what this particular role needs "
        "right now. This wasn't an easy decision, and it isn't a reflection of your overall potential or "
        "qualifications — it came down to fit for this specific position at this specific time.\n\n"
        "We'd genuinely encourage you to apply again for future openings with {company_name} that match "
        "your background — many strong candidates aren't the right fit for one role but are a great fit "
        "for another down the line, and we keep applications on file for that reason.\n\n"
        "Thank you again for your time and interest in {company_name}. We're sorry we can't take this "
        "further right now, and we wish you the very best in your job search and your career ahead.\n\n"
        "Warm regards,\n{company_name}\nHiring Team\n"
    ),
}


# Old built-in template wording from earlier versions of this file — used
# only by load_settings()'s auto-heal check below, to tell "genuinely
# customized by the user" apart from "just happened to get persisted to
# disk because SOME settings save touched this file while these were still
# the defaults." Never edit these to match the new defaults above — they
# need to stay exactly what shipped before, or the auto-heal stops matching.
_LEGACY_TEMPLATE_DEFAULTS = {
    "interview_email_subject_template": "Your {interview_type} Interview with {company_name} — {when}",
    "interview_email_body_template": (
        "Hi {first_name},\n\n"
        "You're scheduled for a {interview_type} interview{job_role_suffix} with {company_name}.\n\n"
        "When: {when}\n"
        "Mode: {mode}\n"
        "{link_or_location}"
        "{notes_line}"
        "\nLooking forward to speaking with you!\n\n"
        "{company_name}\n"
    ),
    "rejection_email_subject_template": "Update on your application{job_role_suffix}",
    "rejection_email_body_template": (
        "Hi {first_name},\n\n"
        "Thank you for applying{job_role_suffix} and for taking the time to share your background with us.\n\n"
        "After careful review, we've decided to move forward with other candidates whose experience more closely "
        "matches what we're looking for at this time. This wasn't an easy call, and we genuinely appreciate the "
        "effort you put into your application.\n\n"
        "We're sorry we can't take this further right now, and we wish you the very best in your search.\n\n"
        "Warm regards,\n{company_name}\n"
    ),
}


def load_settings() -> dict:
    if not os.path.exists(SETTINGS_PATH):
        return dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r") as f:
            data = json.load(f)
        merged = {**DEFAULTS, **data}
        # These 4 keys have no settings UI to edit them, so anything stored
        # for them on disk is stale leftover from before this fix (see
        # save_settings' comment) rather than a genuine customization —
        # always use the current code default instead of whatever's saved.
        for key in _LEGACY_TEMPLATE_DEFAULTS:
            merged[key] = DEFAULTS[key]
        return merged
    except Exception:
        return dict(DEFAULTS)


def save_settings(updates: dict) -> bool:
    try:
        current = load_settings()
        current.update(updates)
        # These 4 keys have no actual settings UI to edit them — any stored
        # value only ever got there by accident (an unrelated settings save,
        # e.g. Company Settings, persists the ENTIRE currently-loaded dict
        # back to disk, template keys included). Persisting them just locks
        # in whatever template wording happened to be the default at the
        # time, forever, even after this file's built-in DEFAULTS are later
        # improved. So: never write them — always compute fresh from
        # DEFAULTS on every load instead.
        for key in _LEGACY_TEMPLATE_DEFAULTS:
            current.pop(key, None)
        with open(SETTINGS_PATH, "w") as f:
            json.dump(current, f, indent=2)
        return True
    except Exception:
        return False
