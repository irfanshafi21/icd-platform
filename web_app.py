"""Fast ICD web application.

This is the migration target for the Streamlit UI.  It deliberately lives
beside app.py until feature parity has been verified.  The API keeps a
separate authenticated Supabase client per browser session so company RLS
tokens are never shared between recruiters.
"""

from __future__ import annotations

import json
import base64
import hashlib
import io
import os
import secrets
import threading
import time
import tomllib
import zipfile
import requests
import qrcode
from PIL import Image, ImageDraw
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from postgrest.types import ReturnMethod
from supabase import Client, create_client

from ai_engine import ask_assistant, check_api_key, generate_interview_questions, parse_and_score
from resume_parser import assess_extraction_confidence, extract_text_from_bytes, heuristic_resume_check
from email_utils import is_configured as email_is_configured, send_email_with_pdf, send_plain_email
from inbox_intake import is_configured as inbox_is_configured, fetch_new_resumes
from reports import (
    build_interview_report_pdf,
    build_candidate_report_pdf,
    build_offer_letter_pdf,
    build_shortlist_report_pdf,
    candidates_to_dataframe,
    df_to_csv_bytes,
    df_to_excel_bytes,
    interviews_to_dataframe,
)

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def _settings() -> dict[str, Any]:
    values: dict[str, Any] = {}
    secret_file = ROOT / ".streamlit" / "secrets.toml"
    if secret_file.exists():
        with secret_file.open("rb") as handle:
            values.update(tomllib.load(handle))
    values.update({key: value for key, value in os.environ.items() if value})
    return values


CONFIG = _settings()
SUPABASE_URL = CONFIG.get("SUPABASE_URL", "")
SUPABASE_KEY = CONFIG.get("SUPABASE_KEY", "")
OWNER_EMAIL = str(CONFIG.get("OWNER_EMAIL", "irfanshafi210608@gmail.com")).strip().lower()


def _is_owner_email(value: Any) -> bool:
    return str(value or "").strip().lower() == OWNER_EMAIL


def _numeric_score(value: Any) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _hiring_average(ats_score: Any, interview_score: Any) -> float | None:
    if interview_score in (None, ""):
        return None
    return round((_numeric_score(ats_score) + _numeric_score(interview_score)) / 2, 1)


def _company_logo(company: dict[str, Any]) -> bytes | None:
    try:
        return base64.b64decode(company.get("logo_base64") or "") or None
    except Exception:
        return None


def _send_company_email(company: dict[str, Any], email: str, subject: str, body: str,
                        badge: str) -> tuple[bool, str]:
    if not email:
        return False, "Candidate email was not captured"
    return send_plain_email(email, subject, body, logo_bytes=_company_logo(company),
                            company_name=company.get("name") or "ICD Platform", badge_text=badge)


def _create_google_meet(company: dict[str, Any], data: dict[str, Any]) -> str:
    """Create a real Meet conference through the deployment's Calendar relay."""
    endpoint = str(CONFIG.get("GOOGLE_CALENDAR_WEBHOOK_URL") or "").strip()
    secret = str(CONFIG.get("GOOGLE_CALENDAR_WEBHOOK_SECRET") or "").strip()
    if not endpoint:
        raise HTTPException(503, "Google Calendar is not connected. Add GOOGLE_CALENDAR_WEBHOOK_URL before scheduling an online interview.")
    try:
        response = requests.post(endpoint, json={"action": "create_interview", "secret": secret,
            "summary": f"Interview: {data['candidate_name']} — {data.get('job_role') or 'Candidate'}",
            "scheduled_at": data["scheduled_at"], "duration_minutes": data.get("duration_minutes", 45),
            "guest_email": data.get("candidate_email") or "", "company": company.get("name") or "ICD Platform",
            "description": data.get("notes") or "Interview scheduled through ICD Platform."}, timeout=25)
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(502, f"Google Calendar could not create the meeting: {exc}") from exc
    link = str(result.get("meeting_link") or result.get("hangoutLink") or "").strip()
    if not link.startswith("https://meet.google.com/"):
        raise HTTPException(502, "Google Calendar did not return a valid Meet link")
    return link


class RecruiterSession:
    def __init__(self, client: Client, company: dict[str, Any]):
        self.client = client
        self.company = company
        self.last_seen = time.monotonic()


class CandidateSession:
    def __init__(self, client: Client, user: Any):
        self.client = client
        self.user = user
        self.last_seen = time.monotonic()


_sessions: dict[str, RecruiterSession] = {}
_candidate_sessions: dict[str, CandidateSession] = {}
_linkedin_states: dict[str, tuple[str, float]] = {}
_sessions_lock = threading.Lock()
SESSION_TTL = 60 * 60 * 12


def _public_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(503, "Supabase is not configured")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _session(icd_session: str | None = Cookie(default=None)) -> RecruiterSession:
    if not icd_session:
        raise HTTPException(401, "Recruiter login required")
    with _sessions_lock:
        session = _sessions.get(icd_session)
        if not session or time.monotonic() - session.last_seen > SESSION_TTL:
            _sessions.pop(icd_session, None)
            raise HTTPException(401, "Recruiter session expired")
        session.last_seen = time.monotonic()
        return session


def _candidate_session(response: Response,
                       icd_candidate_session: str | None = Cookie(default=None),
                       icd_candidate_refresh: str | None = Cookie(default=None)) -> CandidateSession:
    with _sessions_lock:
        session = _candidate_sessions.get(icd_candidate_session)
        if session and time.monotonic() - session.last_seen <= SESSION_TTL:
            session.last_seen = time.monotonic()
            return session
        if icd_candidate_session:
            _candidate_sessions.pop(icd_candidate_session, None)
    if not icd_candidate_refresh:
        raise HTTPException(401, "Candidate login required")
    try:
        client = _public_client()
        refreshed = client.auth.refresh_session(icd_candidate_refresh)
        if not refreshed.user or not refreshed.session:
            raise ValueError("No refreshed session")
    except Exception as exc:
        response.delete_cookie("icd_candidate_refresh")
        raise HTTPException(401, "Candidate session expired") from exc
    session_id = secrets.token_urlsafe(32)
    with _sessions_lock:
        _candidate_sessions[session_id] = CandidateSession(client, refreshed.user)
    _set_candidate_cookies(response, session_id, refreshed.session.refresh_token)
    return _candidate_sessions[session_id]


def _owner_session(session: CandidateSession = Depends(_candidate_session)) -> CandidateSession:
    if str(getattr(session.user, "email", "")).strip().lower() != OWNER_EMAIL:
        raise HTTPException(403, "Owner access required")
    return session


def _set_candidate_cookies(response: Response, session_id: str, refresh_token: str) -> None:
    secure = bool(CONFIG.get("RENDER"))
    response.set_cookie("icd_candidate_session", session_id, httponly=True, secure=secure,
                        samesite="lax", max_age=SESSION_TTL)
    response.set_cookie("icd_candidate_refresh", refresh_token, httponly=True, secure=secure,
                        samesite="lax", max_age=60 * 60 * 24 * 30)


def _company_query(session: RecruiterSession, table: str):
    return session.client.table(table).select("*").eq("company_id", session.company["id"])


def _json_field(value: Any, default):
    if not isinstance(value, str):
        return value if value is not None else default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _candidate(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    profile = _json_field(row.get("profile_json"), {})
    score_data = _json_field(row.get("score_json"), {})
    if not profile:
        profile = {
            "name": row.get("candidate_name"), "email": row.get("email"), "phone": row.get("phone"),
            "years_experience": row.get("years_experience"), "education": row.get("education"),
            "skills": _json_field(row.get("skills"), []),
        }
    if not score_data:
        score_data = {
            "overall_score": row.get("overall_score") or 0,
            "matched_skills": _json_field(row.get("matched_skills"), []),
            "gaps": _json_field(row.get("gaps"), []),
        }
    return {
        **row, "candidate_name": row.get("candidate_name") or profile.get("name") or row.get("filename"),
        "years_experience": profile.get("years_experience"), "education": profile.get("education"),
        "skills": profile.get("skills") or [], "matched_skills": score_data.get("matched_skills") or [],
        "gaps": score_data.get("gaps") or [], "score": score_data.get("overall_score") or 0,
        "decision_status": row.get("decision_status") or "Waiting",
    }


app = FastAPI(title="ICD Platform API", version="2.0")
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    source = Image.open(ROOT / "assets" / "logo_header.png").convert("RGBA")
    alpha_box = source.getchannel("A").getbbox()
    if alpha_box:
        source = source.crop(alpha_box)
    source.thumbnail((108, 72), Image.Resampling.LANCZOS)
    icon = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    tile = Image.new("RGBA", icon.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    draw.rounded_rectangle((4, 4, 124, 124), radius=27, fill="#ffffff",
                           outline="#d6e4ef", width=3)
    icon.alpha_composite(tile)
    icon.alpha_composite(source, ((128 - source.width) // 2, (128 - source.height) // 2))
    output = io.BytesIO()
    icon.save(output, format="PNG", optimize=True)
    output.seek(0)
    return StreamingResponse(output, media_type="image/png",
                             headers={"Cache-Control": "no-cache, no-store, max-age=0"})


@app.get("/api/health")
def health():
    return {"ok": True, "service": "icd-web"}


@app.get("/api/organizations")
def organizations(search: str = ""):
    query = _public_client().table("companies_public").select("*").order("name")
    if search.strip():
        query = query.ilike("name", f"%{search.strip()}%")
    return query.limit(50).execute().data or []


class CompanyRegistration(BaseModel):
    company_name: str = Field(min_length=2, max_length=120)
    contact_name: str = Field(min_length=2, max_length=120)
    business_email: str = Field(min_length=5, max_length=180)
    website: str = Field(default="", max_length=300)
    industry: str = Field(default="", max_length=100)
    company_size: str = Field(default="", max_length=50)
    phone: str = Field(default="", max_length=40)
    registration_number: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=1000)


@app.post("/api/company-registrations")
def register_company(payload: CompanyRegistration):
    email = payload.business_email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter a valid business email")
    row = {**payload.model_dump(), "company_name": payload.company_name.strip(),
           "contact_name": payload.contact_name.strip(), "business_email": email,
           "status": "pending"}
    try:
        _public_client().table("company_registrations").insert(
            row, returning=ReturnMethod.minimal
        ).execute()
    except Exception as exc:
        if "duplicate" in str(exc).lower():
            raise HTTPException(409, "A registration for this email is already under review") from exc
        raise HTTPException(400, "Could not submit the registration") from exc
    return {"ok": True, "message": "Registration submitted for owner review"}


def _company_branding(client: Client, company_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not company_ids:
        return {}
    rows = client.table("companies_public").select("*").in_("id", list(company_ids)).execute().data or []
    return {str(row["id"]): row for row in rows}


@app.get("/api/public/jobs")
def public_jobs(search: str = ""):
    client = _public_client()
    query = (client.table("jobs").select("*").eq("status", "active")
             .eq("published_to_portal", True).order("created_at", desc=True))
    if search.strip():
        query = query.ilike("title", f"%{search.strip()}%")
    jobs = query.limit(200).execute().data or []
    brands = _company_branding(client, {str(j.get("company_id")) for j in jobs if j.get("company_id")})
    return [{**job, "company": brands.get(str(job.get("company_id")), {})} for job in jobs]


@app.get("/api/public/jobs/{job_id}")
def public_job(job_id: int):
    client = _public_client()
    rows = (client.table("jobs").select("*").eq("id", job_id).eq("status", "active")
            .eq("published_to_portal", True).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "This job is no longer available")
    job = rows[0]
    brands = _company_branding(client, {str(job.get("company_id"))})
    return {**job, "company": brands.get(str(job.get("company_id")), {})}


class CandidateOtp(BaseModel):
    email: str


@app.post("/api/candidate/send-otp")
def candidate_send_otp(payload: CandidateOtp):
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter a valid email address")
    _public_client().auth.sign_in_with_otp({"email": email})
    return {"ok": True, "email": email}


class CandidateVerify(CandidateOtp):
    token: str


@app.post("/api/candidate/verify-otp")
def candidate_verify_otp(payload: CandidateVerify, response: Response):
    client = _public_client()
    verified = client.auth.verify_otp({
        "email": payload.email.strip().lower(), "token": payload.token.strip(), "type": "email"
    })
    if not verified.user:
        raise HTTPException(401, "The verification code is incorrect or expired")
    session_id = secrets.token_urlsafe(32)
    with _sessions_lock:
        _candidate_sessions[session_id] = CandidateSession(client, verified.user)
    if not verified.session:
        raise HTTPException(401, "Could not create a secure candidate session")
    _set_candidate_cookies(response, session_id, verified.session.refresh_token)
    return {"ok": True, "destination": "owner" if _is_owner_email(getattr(verified.user, "email", "")) else "candidate"}


@app.get("/api/candidate/google")
def candidate_google(request: Request, owner: bool = False):
    # Keep candidates inside the polished login flow if Google has not yet
    # been enabled for this Supabase project.
    try:
        settings = requests.get(
            f"{SUPABASE_URL.rstrip('/')}/auth/v1/settings",
            headers={"apikey": SUPABASE_KEY},
            timeout=5,
        ).json()
        if not settings.get("external", {}).get("google", False):
            return RedirectResponse("/?candidate=1&auth_error=google_not_configured", status_code=302)
    except Exception:
        return RedirectResponse("/?candidate=1&auth_error=google_unavailable", status_code=302)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    origin = str(request.base_url).rstrip("/")
    callback = f"{origin}/api/candidate/oauth/callback"
    authorize = f"{SUPABASE_URL.rstrip('/')}/auth/v1/authorize?" + urlencode({
        "provider": "google", "redirect_to": callback,
        "code_challenge": challenge, "code_challenge_method": "s256",
    })
    response = RedirectResponse(authorize, status_code=302)
    response.set_cookie("icd_oauth_verifier", verifier, httponly=True,
                        secure=bool(CONFIG.get("RENDER")), samesite="lax", max_age=600)
    response.set_cookie("icd_oauth_destination", "owner" if owner else "candidate", httponly=True,
                        secure=bool(CONFIG.get("RENDER")), samesite="lax", max_age=600)
    return response


@app.get("/api/candidate/oauth/callback")
def candidate_oauth_callback(code: str, request: Request,
                             icd_oauth_verifier: str | None = Cookie(default=None),
                             icd_oauth_destination: str | None = Cookie(default=None)):
    if not icd_oauth_verifier:
        return RedirectResponse("/?candidate=1&auth_error=oauth_expired", status_code=302)
    try:
        client = _public_client()
        verified = client.auth.exchange_code_for_session({
            "auth_code": code, "code_verifier": icd_oauth_verifier,
            "redirect_to": str(request.url).split("?", 1)[0],
        })
        if not verified.user or not verified.session:
            raise ValueError("Google did not return a session")
    except Exception:
        return RedirectResponse("/?candidate=1&auth_error=google_login_failed", status_code=302)
    session_id = secrets.token_urlsafe(32)
    with _sessions_lock:
        _candidate_sessions[session_id] = CandidateSession(client, verified.user)
    destination = "/?owner=1" if (icd_oauth_destination == "owner" or _is_owner_email(getattr(verified.user, "email", ""))) else "/?candidate=1&google_login=success"
    response = RedirectResponse(destination, status_code=302)
    response.delete_cookie("icd_oauth_verifier")
    response.delete_cookie("icd_oauth_destination")
    _set_candidate_cookies(response, session_id, verified.session.refresh_token)
    return response


class OwnerDecision(BaseModel):
    decision: str
    notes: str = Field(default="", max_length=1000)


@app.get("/api/owner/registrations")
def owner_registrations(session: CandidateSession = Depends(_owner_session)):
    registrations = (session.client.table("company_registrations").select("*")
                     .order("created_at", desc=True).execute().data or [])
    companies = (_public_client().table("companies_public").select("*").order("name").execute().data or [])
    return {"owner_email": OWNER_EMAIL, "registrations": registrations, "companies": companies}


@app.post("/api/owner/registrations/{registration_id}/decision")
def decide_registration(registration_id: str, payload: OwnerDecision,
                        session: CandidateSession = Depends(_owner_session)):
    decision = payload.decision.strip().lower()
    if decision not in {"approved", "rejected"}:
        raise HTTPException(400, "Decision must be approved or rejected")
    rows = (session.client.table("company_registrations").select("*").eq("id", registration_id)
            .limit(1).execute().data or [])
    if not rows or rows[0].get("status") != "pending":
        raise HTTPException(404, "Pending registration not found")
    registration = rows[0]
    update = {"status": decision, "review_notes": payload.notes.strip(),
              "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if decision == "approved":
        internal_email = f"org-{secrets.token_hex(12)}@login.icd-platform.internal"
        internal_password = secrets.token_urlsafe(36)
        access_code = f"{secrets.randbelow(10000):04d}"
        company_client = _public_client()
        auth_result = company_client.auth.sign_up({"email": internal_email, "password": internal_password})
        if not auth_result.user or not auth_result.session:
            raise HTTPException(500, "Could not provision the organization account")
        company_row = {
            "owner_user_id": str(auth_result.user.id), "name": registration["company_name"],
            "website": registration.get("website") or "", "industry": registration.get("industry") or "",
            "company_size": registration.get("company_size") or "", "access_code": access_code,
            "internal_auth_email": internal_email, "internal_auth_password": internal_password,
            "verification_status": "approved", "billing_plan": "starter_trial",
            "approved_at": update["reviewed_at"], "approved_by": OWNER_EMAIL,
        }
        created = company_client.table("companies").insert(company_row).execute().data or []
        if not created:
            raise HTTPException(500, "Could not create the approved organization")
        update.update({"company_id": created[0]["id"], "access_code": access_code})
    session.client.table("company_registrations").update(update).eq("id", registration_id).execute()
    return {"ok": True, "status": decision, "access_code": update.get("access_code")}


@app.delete("/api/candidate/session")
def candidate_logout(response: Response, icd_candidate_session: str | None = Cookie(default=None)):
    if icd_candidate_session:
        with _sessions_lock:
            _candidate_sessions.pop(icd_candidate_session, None)
    response.delete_cookie("icd_candidate_session")
    response.delete_cookie("icd_candidate_refresh")
    return {"ok": True}


@app.get("/api/candidate/me")
def candidate_me(session: CandidateSession = Depends(_candidate_session)):
    if _is_owner_email(getattr(session.user, "email", "")):
        return {"email": getattr(session.user, "email", ""), "role": "owner"}
    user_id = str(session.user.id)
    profiles = session.client.table("candidate_profiles").select("*").eq("user_id", user_id).limit(1).execute().data or []
    applications = (session.client.table("public_applications")
                    .select("id,status,applied_at,resume_filename,job_id,jobs(title,location,employment_type,company_id)")
                    .eq("candidate_user_id", user_id).order("applied_at", desc=True).execute().data or [])
    jobs = public_jobs()
    return {"email": getattr(session.user, "email", ""), "profile": profiles[0] if profiles else None,
            "applications": applications, "jobs": jobs}


class CandidateProfile(BaseModel):
    full_name: str
    phone: str = ""


@app.put("/api/candidate/profile")
def candidate_profile(payload: CandidateProfile, session: CandidateSession = Depends(_candidate_session)):
    row = {"user_id": str(session.user.id), "full_name": payload.full_name.strip(),
           "email": getattr(session.user, "email", ""), "phone": payload.phone.strip()}
    saved = session.client.table("candidate_profiles").upsert(row, on_conflict="user_id").execute().data or []
    return saved[0] if saved else row


@app.post("/api/candidate/applications")
async def candidate_apply(job_id: int = Form(...), full_name: str = Form(...), phone: str = Form(""),
                          resume: UploadFile = File(...), session: CandidateSession = Depends(_candidate_session)):
    job = public_job(job_id)
    content = await resume.read()
    if not content or len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "Upload a resume smaller than 20 MB")
    filename = resume.filename or "resume.pdf"
    if Path(filename).suffix.lower() not in {".pdf", ".docx"}:
        raise HTTPException(400, "Only PDF and DOCX resumes are supported")
    user_id = str(session.user.id)
    existing = (session.client.table("public_applications").select("id").eq("candidate_user_id", user_id)
                .eq("job_id", job_id).limit(1).execute().data or [])
    if existing:
        raise HTTPException(409, "You have already applied for this job")
    row = {"job_id": job_id, "company_id": job.get("company_id"), "candidate_user_id": user_id,
           "applicant_name": full_name.strip(), "applicant_email": getattr(session.user, "email", ""),
           "applicant_phone": phone.strip(), "resume_filename": filename,
           "resume_base64": base64.b64encode(content).decode("ascii"), "status": "Submitted"}
    saved = session.client.table("public_applications").insert(row).execute().data or []
    if not saved:
        raise HTTPException(500, "The application could not be submitted")
    return {"ok": True, "application": saved[0]}


class RecruiterLogin(BaseModel):
    company_id: str
    access_code: str


@app.post("/api/session/recruiter")
def recruiter_login(payload: RecruiterLogin, response: Response):
    client = _public_client()
    result = client.rpc(
        "get_company_login",
        {"p_company_id": payload.company_id, "p_code": payload.access_code.strip()},
    ).execute()
    rows = result.data or []
    if not rows:
        raise HTTPException(401, "The organization or access code is incorrect")
    auth_row = rows[0]
    login = client.auth.sign_in_with_password(
        {"email": auth_row.get("auth_email"), "password": auth_row.get("auth_password")}
    )
    if not login.user:
        raise HTTPException(401, "Organization login failed")
    company_rows = client.table("companies").select("*").eq("id", payload.company_id).limit(1).execute().data or []
    if not company_rows:
        raise HTTPException(404, "Organization was not found")
    session_id = secrets.token_urlsafe(32)
    with _sessions_lock:
        _sessions[session_id] = RecruiterSession(client, company_rows[0])
    response.set_cookie(
        "icd_session", session_id, httponly=True, secure=bool(CONFIG.get("RENDER")),
        samesite="lax", max_age=SESSION_TTL
    )
    return {"company": company_rows[0]}


@app.delete("/api/session")
def logout(response: Response, icd_session: str | None = Cookie(default=None)):
    if icd_session:
        with _sessions_lock:
            session = _sessions.pop(icd_session, None)
        if session:
            try:
                session.client.auth.sign_out()
            except Exception:
                pass
    response.delete_cookie("icd_session")
    return {"ok": True}


@app.get("/api/bootstrap")
def bootstrap(session: RecruiterSession = Depends(_session)):
    company_id = session.company["id"]
    jobs = (session.client.table("jobs").select("*").eq("company_id", company_id)
            .order("created_at", desc=True).execute().data or [])
    candidates = (session.client.table("screening_history").select("*").eq("company_id", company_id)
                  .neq("status", "cleared").order("screened_at", desc=True).limit(1000).execute().data or [])
    interviews = (session.client.table("interviews").select("*").eq("company_id", company_id)
                  .order("scheduled_at").limit(500).execute().data or [])
    applications = (session.client.table("public_applications")
                    .select("id,job_id,company_id,applicant_name,applicant_email,applicant_phone,resume_filename,status,applied_at")
                    .eq("company_id", company_id).order("applied_at", desc=True).limit(1000).execute().data or [])
    try:
        linkedin_connection = (session.client.table("linkedin_connections").select("member_name,expires_at")
                               .eq("company_id", company_id).limit(1).execute().data or [])
    except Exception:
        linkedin_connection = []
    parsed = [_candidate(row) for row in candidates]
    return {
        "company": session.company,
        "jobs": jobs,
        "candidates": parsed,
        "interviews": interviews,
        "applications": applications,
        "integrations": {
            "ai": check_api_key(),
            "email": email_is_configured(),
            "resume_inbox": inbox_is_configured(),
            "google_candidate_login": bool(SUPABASE_URL and SUPABASE_KEY),
            "google_calendar": bool(CONFIG.get("GOOGLE_CALENDAR_WEBHOOK_URL")),
            "linkedin": bool(linkedin_connection),
            "linkedin_configured": bool(CONFIG.get("LINKEDIN_CLIENT_ID") and CONFIG.get("LINKEDIN_CLIENT_SECRET")),
            "linkedin_member": linkedin_connection[0].get("member_name") if linkedin_connection else "",
        },
        "summary": {
            "active_jobs": sum(job.get("status") == "active" for job in jobs),
            "candidates": len(parsed),
            "shortlisted": sum(candidate["score"] > 49 for candidate in parsed),
            "selected": sum(candidate.get("decision_status") == "Selected" for candidate in parsed),
            "scheduled_interviews": sum(item.get("status") == "Scheduled" for item in interviews),
            "applications": len(applications),
        },
    }


class JobPayload(BaseModel):
    title: str
    department: str = ""
    location: str = ""
    employment_type: str = "Full-time"
    experience_level: str = ""
    description: str = ""
    responsibilities: str = ""
    benefits: str = ""
    required_skills: list[str] = Field(default_factory=list)


class JobImportPayload(BaseModel):
    jobs: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/api/jobs/export")
def export_jobs(session: RecruiterSession = Depends(_session)):
    rows = (_company_query(session, "jobs").order("created_at", desc=True).execute().data or [])
    content = json.dumps(rows, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    return StreamingResponse(io.BytesIO(content), media_type="application/json",
                             headers={"Content-Disposition": 'attachment; filename="ICD-jobs.json"'})


@app.post("/api/jobs/import")
def import_jobs(payload: JobImportPayload, session: RecruiterSession = Depends(_session)):
    allowed = set(JobPayload.model_fields)
    rows = []
    for item in payload.jobs[:200]:
        cleaned = {key: item.get(key) for key in allowed if item.get(key) is not None}
        if not str(cleaned.get("title", "")).strip():
            continue
        cleaned.update({"company_id": session.company["id"], "status": item.get("status", "active"),
                        "published_to_portal": item.get("published_to_portal", True)})
        rows.append(cleaned)
    if rows:
        session.client.table("jobs").insert(rows).execute()
    return {"imported": len(rows)}


@app.post("/api/jobs")
def create_job(payload: JobPayload, session: RecruiterSession = Depends(_session)):
    row = {**payload.model_dump(), "company_id": session.company["id"], "status": "active",
           "published_to_portal": True}
    result = session.client.table("jobs").insert(row).execute().data or []
    if not result:
        raise HTTPException(500, "The job could not be saved")
    return result[0]


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    result = (session.client.table("jobs").update(payload).eq("id", job_id)
              .eq("company_id", session.company["id"]).execute().data or [])
    return result[0] if result else {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int, session: RecruiterSession = Depends(_session)):
    (session.client.table("jobs").delete().eq("id", job_id)
     .eq("company_id", session.company["id"]).execute())
    return {"ok": True}


@app.patch("/api/company")
def update_company(payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    allowed = {key: value for key, value in payload.items()
               if key in {"name", "industry", "website", "company_size", "logo_base64"}}
    if not allowed:
        raise HTTPException(400, "No supported company fields were supplied")
    rows = (session.client.table("companies").update(allowed).eq("id", session.company["id"])
            .execute().data or [])
    if rows:
        session.company = rows[0]
    return session.company


@app.post("/api/company/access-code")
def change_access_code(payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    code = str(payload.get("access_code", "")).strip()
    if not (code.isdigit() and len(code) == 4):
        raise HTTPException(400, "Access code must contain exactly four digits")
    rows = (session.client.table("companies").update({"access_code": code})
            .eq("id", session.company["id"]).execute().data or [])
    if rows:
        session.company = rows[0]
    return {"ok": True}


@app.get("/api/reports/{report_type}.{file_type}")
def export_report(report_type: str, file_type: str, role: str = "",
                  session: RecruiterSession = Depends(_session)):
    candidates = [_candidate(row) for row in
                  ((_company_query(session, "screening_history").neq("status", "cleared")
                    .order("screened_at", desc=True).limit(1000).execute().data) or [])]
    interviews = ((_company_query(session, "interviews").order("scheduled_at").limit(500)
                   .execute().data) or [])
    if role:
        candidates = [item for item in candidates if item.get("job_role") == role]
        interviews = [item for item in interviews if item.get("job_role") == role]
    if report_type == "interviews":
        records, frame = interviews, interviews_to_dataframe(interviews)
    else:
        records = [item for item in candidates if report_type == "screened" or
                   (report_type == "shortlisted" and item.get("score", 0) >= 70) or
                   (report_type == "selected" and item.get("decision_status") == "Selected")]
        legacy = [{"name": item.get("candidate_name"),
                   "profile": _json_field(item.get("profile_json"), {}),
                   "score": _json_field(item.get("score_json"), {"overall_score": item.get("score", 0)})}
                  for item in records]
        frame = candidates_to_dataframe(legacy)
    filename = f"ICD-{report_type}-{role or 'all-roles'}".replace(" ", "-")
    if file_type == "csv":
        return StreamingResponse(io.BytesIO(df_to_csv_bytes(frame)), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'})
    if file_type == "xlsx":
        return StreamingResponse(io.BytesIO(df_to_excel_bytes(frame, report_type.title())),
                                 media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'})
    if file_type == "pdf":
        if report_type == "interviews":
            content = build_interview_report_pdf(records, role or None)
        else:
            content = build_shortlist_report_pdf(legacy, role or "All roles")
        return StreamingResponse(io.BytesIO(content), media_type="application/pdf",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})
    raise HTTPException(400, "Choose csv, xlsx or pdf")


def _application_row(application_id: int, session: RecruiterSession, include_resume: bool = False):
    fields = "*" if include_resume else "id,job_id,company_id,applicant_name,applicant_email,applicant_phone,resume_filename,status,applied_at"
    rows = (session.client.table("public_applications").select(fields).eq("id", application_id)
            .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Application not found")
    return rows[0]


@app.get("/api/applications/{application_id}/resume")
def application_resume(application_id: int, session: RecruiterSession = Depends(_session)):
    row = _application_row(application_id, session, True)
    try:
        content = base64.b64decode(row.get("resume_base64") or "", validate=True)
    except Exception as exc:
        raise HTTPException(404, "Resume file is unavailable") from exc
    name = row.get("resume_filename") or "resume.pdf"
    return StreamingResponse(io.BytesIO(content), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{name.replace(chr(34), "")}"'})


@app.patch("/api/applications/{application_id}")
def update_application(application_id: int, payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    status = str(payload.get("status", "")).strip()
    if status not in {"Submitted", "Screening", "Shortlisted", "Interview", "Selected", "Rejected"}:
        raise HTTPException(400, "Unsupported application status")
    _application_row(application_id, session)
    rows = (session.client.table("public_applications").update({"status": status}).eq("id", application_id)
            .eq("company_id", session.company["id"]).execute().data or [])
    return rows[0] if rows else {"ok": True}


@app.delete("/api/applications/{application_id}")
def delete_application(application_id: int, session: RecruiterSession = Depends(_session)):
    _application_row(application_id, session)
    (session.client.table("public_applications").delete().eq("id", application_id)
     .eq("company_id", session.company["id"]).execute())
    return {"ok": True}


@app.get("/api/jobs/{job_id}/applications.zip")
def applications_zip(job_id: int, session: RecruiterSession = Depends(_session)):
    owned = (session.client.table("jobs").select("id,title").eq("id", job_id)
             .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not owned:
        raise HTTPException(404, "Job not found")
    rows = (session.client.table("public_applications").select("id,applicant_name,resume_filename,resume_base64")
            .eq("job_id", job_id).eq("company_id", session.company["id"]).execute().data or [])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, row in enumerate(rows, 1):
            try:
                content = base64.b64decode(row.get("resume_base64") or "", validate=True)
            except Exception:
                continue
            safe_name = "".join(c for c in (row.get("applicant_name") or f"candidate-{index}") if c.isalnum() or c in " -_").strip()
            ext = Path(row.get("resume_filename") or ".pdf").suffix or ".pdf"
            archive.writestr(f"{safe_name or f'candidate-{index}'}{ext}", content)
    output.seek(0)
    filename = "".join(c for c in owned[0]["title"] if c.isalnum() or c in "-_") or "applications"
    return StreamingResponse(output, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{filename}-applications.zip"'})


@app.get("/api/jobs/{job_id}/qr")
def job_qr(job_id: int, request: Request, session: RecruiterSession = Depends(_session)):
    owned = (session.client.table("jobs").select("id").eq("id", job_id)
             .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not owned:
        raise HTTPException(404, "Job not found")
    url = f"{str(request.base_url).rstrip('/')}?apply={job_id}"
    image = qrcode.make(url)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png",
                             headers={"Content-Disposition": f'inline; filename="job-{job_id}-qr.png"'})


@app.patch("/api/candidates/{candidate_id}")
def update_candidate(candidate_id: int, payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    allowed = {
        ("decision_status" if key == "status" else key): value
        for key, value in payload.items() if key in {"status", "notes", "interview_score", "email", "phone"}
    }
    if not allowed:
        raise HTTPException(400, "No supported fields were supplied")
    existing = (session.client.table("screening_history").select("*").eq("id", candidate_id)
                .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not existing:
        raise HTTPException(404, "Candidate not found")
    candidate = existing[0]
    requested_status = allowed.get("decision_status")
    if requested_status == "Shortlisted" and _numeric_score(candidate.get("overall_score")) <= 49:
        raise HTTPException(400, "Only candidates with an ATS score above 49 can be approved for interview")
    if requested_status == "Selected":
        average = _hiring_average(candidate.get("overall_score"), candidate.get("interview_score"))
        if average is None or average <= 70:
            raise HTTPException(400, "An ATS/interview average above 70 is required before offer selection")
    if "interview_score" in allowed and candidate.get("interview_score") not in (None, ""):
        raise HTTPException(409, "The interview score is locked and cannot be changed")
    result = (session.client.table("screening_history").update(allowed).eq("id", candidate_id)
              .eq("company_id", session.company["id"]).execute().data or [])
    if requested_status == "Rejected":
        email = candidate.get("email") or _json_field(candidate.get("profile_json"), {}).get("email") or ""
        role = candidate.get("job_role") or "the position"
        company_name = session.company.get("name") or "the hiring company"
        _send_company_email(session.company, email, f"Update on your application for {role}",
            f"Hello {candidate.get('candidate_name') or 'Candidate'},\n\nThank you for the time and effort you invested in applying for {role} at {company_name}. After reviewing your application against the role requirements, the hiring team will not be moving forward with your application at this stage.\n\nThis decision applies only to this position. We appreciate your interest and wish you every success in your job search.\n\nRegards,\n{company_name} Hiring Team", "Application update")
        if email:
            query = session.client.table("public_applications").update({"status": "Rejected"}).eq("company_id", session.company["id"]).eq("applicant_email", email)
            if candidate.get("job_id"):
                query = query.eq("job_id", candidate["job_id"])
            query.execute()
    return _candidate(result[0]) if result else {"ok": True}


@app.delete("/api/candidates")
def clear_candidates(session: RecruiterSession = Depends(_session)):
    session.client.table("screening_history").update({"status": "cleared"}).eq("company_id", session.company["id"]).execute()
    return {"ok": True}


@app.post("/api/candidates/{candidate_id}/ats-rerun")
def rerun_candidate_ats(candidate_id: int, session: RecruiterSession = Depends(_session)):
    rows = (session.client.table("screening_history").select("*").eq("id", candidate_id)
            .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Candidate not found")
    row = rows[0]
    if not (row.get("raw_text") or "").strip():
        raise HTTPException(400, "The original resume text is unavailable")
    try:
        profile, score = parse_and_score(row["raw_text"], f"Job Role: {row.get('job_role') or ''}\n\n{row.get('job_details') or ''}")
    except Exception as exc:
        raise HTTPException(503, f"ATS analysis is temporarily unavailable: {exc}") from exc
    profile["extraction_flags"] = assess_extraction_confidence(profile, row["raw_text"])
    decision = row.get("decision_status")
    if decision not in {"Rejected", "Selected", "Interview Scheduled", "Interview Completed"}:
        decision = "Interview Eligible" if _numeric_score(score.get("overall_score")) > 49 else "Waiting"
    values = {"profile_json": json.dumps(profile), "score_json": json.dumps(score),
              "overall_score": score.get("overall_score", 0),
              "skills_match": (score.get("breakdown") or {}).get("skills_match"),
              "experience_fit": (score.get("breakdown") or {}).get("experience_fit"),
              "education_fit": (score.get("breakdown") or {}).get("education_fit"),
              "matched_skills": json.dumps(score.get("matched_skills") or []),
              "gaps": json.dumps(score.get("gaps") or []), "recruiter_summary": score.get("summary"),
              "decision_status": decision}
    updated = (session.client.table("screening_history").update(values).eq("id", candidate_id)
               .eq("company_id", session.company["id"]).execute().data or [])
    return _candidate(updated[0] if updated else {**row, **values})


@app.get("/api/candidates/{candidate_id}/report.pdf")
def candidate_report(candidate_id: int, session: RecruiterSession = Depends(_session)):
    rows = (session.client.table("screening_history").select("*").eq("id", candidate_id)
            .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Candidate not found")
    row = rows[0]
    pdf = build_candidate_report_pdf({"name": row.get("candidate_name") or row.get("filename") or "Candidate",
                                      "profile": _json_field(row.get("profile_json"), {}),
                                      "score": _json_field(row.get("score_json"), {})},
                                     row.get("job_role") or "", row.get("job_details") or "")
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="candidate-{candidate_id}-report.pdf"'})


class InterviewPayload(BaseModel):
    candidate_id: int | None = None
    candidate_name: str
    candidate_email: str = ""
    job_role: str = ""
    interview_type: str = "Technical"
    scheduled_at: str
    duration_minutes: int = 45
    mode: str = "Online"
    location: str = ""
    meeting_link: str = ""
    notes: str = ""


@app.post("/api/interviews")
def create_interview(payload: InterviewPayload, session: RecruiterSession = Depends(_session)):
    data = payload.model_dump()
    if payload.candidate_id is None:
        raise HTTPException(400, "Choose a screened candidate")
    candidates = (session.client.table("screening_history").select("*").eq("id", payload.candidate_id)
                  .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not candidates:
        raise HTTPException(404, "Candidate not found")
    candidate = candidates[0]
    if _numeric_score(candidate.get("overall_score")) <= 49:
        raise HTTPException(400, "This candidate needs an ATS score above 49")
    if (candidate.get("decision_status") or "") == "Rejected":
        raise HTTPException(400, "A rejected candidate cannot be scheduled for interview")
    if payload.mode.lower() == "online":
        data["meeting_link"] = _create_google_meet(session.company, data)
    row = {key: data[key] for key in (
        "candidate_name", "job_role", "interview_type", "scheduled_at", "mode", "location",
        "meeting_link", "notes"
    )}
    row.update({"company_id": session.company["id"], "status": "Scheduled"})
    rows = session.client.table("interviews").insert(row).execute().data or []
    if not rows:
        raise HTTPException(500, "Interview could not be scheduled")
    session.client.table("screening_history").update({"decision_status": "Interview Scheduled"}).eq("id", payload.candidate_id).eq("company_id", session.company["id"]).execute()
    email = candidate.get("email") or payload.candidate_email
    company_name = session.company.get("name") or "the hiring company"
    when = payload.scheduled_at.replace("T", " ")
    venue = data.get("meeting_link") if payload.mode.lower() == "online" else data.get("location")
    _send_company_email(session.company, email, f"Interview scheduled — {payload.job_role} at {company_name}",
        f"Hello {payload.candidate_name},\n\nYour application has progressed to the interview stage for {payload.job_role or 'the position'} at {company_name}.\n\nInterview type: {payload.interview_type}\nDate and time: {when}\nDuration: {payload.duration_minutes} minutes\nMode: {payload.mode}\n{'Google Meet link' if payload.mode.lower() == 'online' else 'Location'}: {venue}\n\nPlease join a few minutes early and reply to this email if you need assistance. Your candidate portal status has also been updated.\n\nRegards,\n{company_name} Hiring Team", "Interview invitation")
    if email:
        query = session.client.table("public_applications").update({"status": "Interview Scheduled"}).eq("company_id", session.company["id"]).eq("applicant_email", email)
        if candidate.get("job_id"):
            query = query.eq("job_id", candidate["job_id"])
        query.execute()
    return {**rows[0], "meeting_link": data.get("meeting_link", "")}


@app.patch("/api/interviews/{interview_id}")
def update_interview(interview_id: int, payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    allowed = {k: v for k, v in payload.items() if k in {
        "status", "scheduled_at", "duration_minutes", "mode", "location", "meeting_link",
        "notes", "interview_score", "interview_type"
    }}
    if not allowed:
        raise HTTPException(400, "No supported fields were supplied")
    current = (session.client.table("interviews").select("*").eq("id", interview_id)
               .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not current:
        raise HTTPException(404, "Interview not found")
    interview = current[0]
    if "interview_score" in allowed:
        if interview.get("interview_score") not in (None, ""):
            raise HTTPException(409, "The interview score is locked and cannot be changed")
        score = _numeric_score(allowed["interview_score"])
        allowed["interview_score"] = score
        allowed["status"] = "Completed"
    rows = (session.client.table("interviews").update(allowed).eq("id", interview_id)
            .eq("company_id", session.company["id"]).execute().data or [])
    if "interview_score" in allowed:
        matches = (session.client.table("screening_history").select("*").eq("company_id", session.company["id"])
                   .eq("candidate_name", interview.get("candidate_name")).eq("job_role", interview.get("job_role")).limit(1).execute().data or [])
        if matches:
            candidate = matches[0]
            average = _hiring_average(candidate.get("overall_score"), allowed["interview_score"])
            decision = "Selected" if average is not None and average > 70 else "Interview Completed"
            session.client.table("screening_history").update({"interview_score": allowed["interview_score"], "decision_status": decision}).eq("id", candidate["id"]).eq("company_id", session.company["id"]).execute()
    return rows[0] if rows else {"ok": True}


@app.delete("/api/interviews/{interview_id}")
def delete_interview(interview_id: int, session: RecruiterSession = Depends(_session)):
    (session.client.table("interviews").delete().eq("id", interview_id)
     .eq("company_id", session.company["id"]).execute())
    return {"ok": True}


@app.delete("/api/interview-actions/clear")
def clear_interviews(session: RecruiterSession = Depends(_session)):
    session.client.table("interviews").delete().eq("company_id", session.company["id"]).execute()
    return {"ok": True}


class InsightPayload(BaseModel):
    question: str
    chat_history: list[dict[str, Any]] = Field(default_factory=list)


@app.post("/api/insights")
def generate_insight(payload: InsightPayload, session: RecruiterSession = Depends(_session)):
    rows = (session.client.table("screening_history").select("*").eq("company_id", session.company["id"])
            .neq("status", "cleared").order("screened_at", desc=True).limit(300).execute().data or [])
    candidates = [_candidate(row) for row in rows]
    try:
        answer = ask_assistant(payload.question.strip(), candidates, "All active roles", "", payload.chat_history[-12:])
    except Exception as exc:
        raise HTTPException(503, f"AI insight is temporarily unavailable: {exc}") from exc
    return {"answer": answer}


class InterviewQuestionsPayload(BaseModel):
    candidate_id: int


@app.post("/api/interview-questions")
def interview_questions(payload: InterviewQuestionsPayload, session: RecruiterSession = Depends(_session)):
    rows = (session.client.table("screening_history").select("*").eq("id", payload.candidate_id)
            .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not rows:
        raise HTTPException(404, "Candidate not found")
    row = rows[0]
    try:
        result = generate_interview_questions(_json_field(row.get("profile_json"), {}),
                                              _json_field(row.get("score_json"), {}),
                                              row.get("job_details") or row.get("job_role") or "")
    except Exception as exc:
        raise HTTPException(503, f"Interview preparation is temporarily unavailable: {exc}") from exc
    return result


class OfferBatchPayload(BaseModel):
    candidate_ids: list[int]
    job_title: str = ""
    salary: str = ""
    start_date: str = ""
    location: str = ""
    reporting_manager: str = ""
    acceptance_deadline: str = ""
    hr_name: str = "Hiring Manager"
    employment_type: str = "Full-time"
    work_schedule: str = ""
    probation_period: str = ""
    benefits: str = ""
    signature_style: str = ""


def _offer_pdf_for(row: dict[str, Any], payload: OfferBatchPayload, company: dict[str, Any]) -> bytes:
    candidate = _candidate(row)
    offer = {**payload.model_dump(exclude={"candidate_ids"}),
             "job_title": payload.job_title or row.get("job_role") or "Position",
             "company_name": company.get("name") or "Our Company",
             "company_email": company.get("email") or ""}
    logo = _company_logo(company)
    return build_offer_letter_pdf({"name": candidate["candidate_name"],
                                   "profile": _json_field(row.get("profile_json"), {}),
                                   "score": _json_field(row.get("score_json"), {})}, offer, logo_bytes=logo)


@app.post("/api/offers/preview.pdf")
def preview_offer(payload: OfferBatchPayload, session: RecruiterSession = Depends(_session)):
    if not payload.candidate_ids:
        raise HTTPException(400, "Choose a candidate to preview")
    rows = (session.client.table("screening_history").select("*").eq("id", payload.candidate_ids[0])
            .eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not rows or rows[0].get("decision_status") != "Selected" or (_hiring_average(rows[0].get("overall_score"), rows[0].get("interview_score")) or 0) <= 70:
        raise HTTPException(400, "This candidate is not eligible for an offer")
    return StreamingResponse(io.BytesIO(_offer_pdf_for(rows[0], payload, session.company)), media_type="application/pdf",
                             headers={"Content-Disposition": 'inline; filename="offer-preview.pdf"'})


@app.post("/api/offers.zip")
def offer_letters(payload: OfferBatchPayload, session: RecruiterSession = Depends(_session)):
    if not payload.candidate_ids:
        raise HTTPException(400, "Choose at least one selected candidate")
    rows = (session.client.table("screening_history").select("*").in_("id", payload.candidate_ids)
            .eq("company_id", session.company["id"]).execute().data or [])
    chosen = [row for row in rows if (row.get("decision_status") or "") == "Selected"
              and (_hiring_average(row.get("overall_score"), row.get("interview_score")) or 0) > 70]
    if not chosen:
        raise HTTPException(400, "No selected candidates were found")
    company = session.company
    logo_bytes = None
    if company.get("logo_base64"):
        try:
            logo_bytes = base64.b64decode(company["logo_base64"])
        except Exception:
            pass
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in chosen:
            candidate = _candidate(row)
            report_candidate = {
                "name": candidate["candidate_name"],
                "profile": _json_field(row.get("profile_json"), {"email": row.get("email")}),
                "score": _json_field(row.get("score_json"), {}),
            }
            offer = {
                **payload.model_dump(exclude={"candidate_ids"}),
                "job_title": payload.job_title or row.get("job_role") or "Position",
                "company_name": company.get("name") or "Our Company",
                "company_email": company.get("email") or "",
            }
            pdf = build_offer_letter_pdf(report_candidate, offer, logo_bytes=logo_bytes)
            safe = "".join(c for c in candidate["candidate_name"] if c.isalnum() or c in " -_").strip()
            archive.writestr(f"Offer - {safe or row['id']}.pdf", pdf)
    output.seek(0)
    return StreamingResponse(output, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="ICD-offer-letters.zip"'})


@app.post("/api/offers/send")
def send_offer_letters(payload: OfferBatchPayload, session: RecruiterSession = Depends(_session)):
    rows = (session.client.table("screening_history").select("*").in_("id", payload.candidate_ids)
            .eq("company_id", session.company["id"]).execute().data or [])
    chosen = [row for row in rows if (row.get("decision_status") or "") == "Selected"
              and (_hiring_average(row.get("overall_score"), row.get("interview_score")) or 0) > 70]
    company, sent, failed = session.company, [], []
    logo_bytes = None
    if company.get("logo_base64"):
        try:
            logo_bytes = base64.b64decode(company["logo_base64"])
        except Exception:
            pass
    for row in chosen:
        candidate = _candidate(row)
        profile = _json_field(row.get("profile_json"), {})
        email = row.get("email") or profile.get("email")
        if not email:
            failed.append({"name": candidate["candidate_name"], "reason": "Email not captured"})
            continue
        offer = {**payload.model_dump(exclude={"candidate_ids"}),
                 "job_title": payload.job_title or row.get("job_role") or "Position",
                 "company_name": company.get("name") or "Our Company",
                 "company_email": company.get("email") or ""}
        report_candidate = {"name": candidate["candidate_name"], "profile": profile,
                            "score": _json_field(row.get("score_json"), {})}
        pdf = build_offer_letter_pdf(report_candidate, offer, logo_bytes=logo_bytes)
        subject = f"Offer for {offer['job_title']} at {offer['company_name']}"
        body = (f"Hello {candidate['candidate_name']},\n\nWe are pleased to offer you the position of "
                f"{offer['job_title']} at {offer['company_name']}.\n\n"
                f"Proposed compensation: {offer.get('salary') or 'See attached offer letter'}\n"
                f"Proposed start date: {offer.get('start_date') or 'To be agreed'}\n"
                f"Reporting manager: {offer.get('reporting_manager') or 'See attached offer letter'}\n"
                f"Acceptance deadline: {offer.get('acceptance_deadline') or 'See attached offer letter'}\n\n"
                "Please read the attached formal offer letter carefully for the complete terms, conditions, and next steps. "
                f"If you have any questions, contact {offer.get('company_email') or 'the hiring team'}.\n\n"
                f"We look forward to welcoming you.\n\nRegards,\n{offer['company_name']} Hiring Team")
        ok, message = send_email_with_pdf(email, subject, body, pdf,
                                          f"Offer - {candidate['candidate_name']}.pdf",
                                          logo_bytes=logo_bytes, company_name=offer["company_name"])
        (sent if ok else failed).append({"name": candidate["candidate_name"],
                                        "email": email, "message": message})
    return {"sent": sent, "failed": failed, "sent_count": len(sent), "failed_count": len(failed)}


def _expand_resume_payloads(payloads: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    expanded: list[tuple[str, bytes]] = []
    for name, data in payloads:
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for member in archive.infolist():
                        safe = Path(member.filename).name
                        if safe and safe.lower().endswith((".pdf", ".docx", ".doc")) and member.file_size <= 20 * 1024 * 1024:
                            expanded.append((safe, archive.read(member)))
            except zipfile.BadZipFile as exc:
                raise HTTPException(400, f"{name} is not a valid ZIP archive") from exc
        elif name.lower().endswith((".pdf", ".docx", ".doc")):
            expanded.append((name, data))
    if len(expanded) > 100:
        raise HTTPException(400, "Upload at most 100 resumes at a time")
    return expanded


def _weighted_score(score: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    breakdown = score.get("breakdown") or {}
    total = sum(max(0, value) for value in weights.values()) or 100
    overall = sum(_numeric_score(breakdown.get(key)) * max(0, value) for key, value in weights.items()) / total
    score["ai_overall_score"] = score.get("overall_score")
    score["overall_score"] = round(overall)
    score["priority_weights"] = {key.replace("_match", "").replace("_fit", ""): round(value / total * 100) for key, value in weights.items()}
    return score


def _screen_payloads(payloads: list[tuple[str, bytes]], job_role: str, job_details: str, job_id: str,
                     weights: dict[str, float], session: RecruiterSession, source: str) -> list[dict[str, Any]]:
    payloads = _expand_resume_payloads(payloads)
    if not check_api_key():
        raise HTTPException(503, "No AI provider is configured")
    extracted: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=min(6, len(payloads))) as pool:
        futures = {pool.submit(extract_text_from_bytes, name, data): name for name, data in payloads}
        for future in as_completed(futures):
            text = future.result()
            if text.strip() and heuristic_resume_check(text).get("looks_like_resume"):
                extracted.append((futures[future], text))
    description = f"Job Role: {job_role}\n\nKey Requirements:\n{job_details}".strip()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(6, len(extracted))) as pool:
        futures = {pool.submit(parse_and_score, text, description): (name, text) for name, text in extracted}
        for future in as_completed(futures):
            name, raw_text = futures[future]
            profile, score = future.result()
            score = _weighted_score(score, weights)
            profile["extraction_flags"] = assess_extraction_confidence(profile, raw_text)
            row = {
                "company_id": session.company["id"], "job_id": int(job_id) if job_id.isdigit() else None,
                "job_role": job_role, "job_details": job_details, "candidate_name": profile.get("name") or name,
                "filename": name, "email": profile.get("email"), "phone": profile.get("phone"),
                "years_experience": profile.get("years_experience"), "education": profile.get("education"),
                "skills": json.dumps(profile.get("skills") or []), "past_roles": json.dumps(profile.get("past_roles") or []),
                "raw_text": raw_text, "profile_json": json.dumps(profile), "score_json": json.dumps(score),
                "overall_score": score.get("overall_score", 0),
                "skills_match": (score.get("breakdown") or {}).get("skills_match"),
                "experience_fit": (score.get("breakdown") or {}).get("experience_fit"),
                "education_fit": (score.get("breakdown") or {}).get("education_fit"),
                "matched_skills": json.dumps(score.get("matched_skills") or []),
                "gaps": json.dumps(score.get("gaps") or []), "recruiter_summary": score.get("summary"),
                "status": "active", "decision_status": ("Interview Eligible" if _numeric_score(score.get("overall_score")) > 49 else "Waiting"), "source": source,
            }
            saved = session.client.table("screening_history").insert(row).execute().data or []
            results.append(_candidate(saved[0] if saved else row))
    return sorted(results, key=lambda item: item["score"], reverse=True)


@app.post("/api/screen")
async def screen_resumes(
    job_role: str = Form(...), job_details: str = Form(""), job_id: str = Form(""),
    skills_weight: float = Form(40), experience_weight: float = Form(40), education_weight: float = Form(20),
    files: list[UploadFile] = File(...), session: RecruiterSession = Depends(_session),
):
    payloads = [(file.filename or "resume.pdf", await file.read()) for file in files]
    results = _screen_payloads(payloads, job_role, job_details, job_id,
                               {"skills_match": skills_weight, "experience_fit": experience_weight, "education_fit": education_weight},
                               session, "Web Upload")
    return {"processed": len(results), "candidates": results}


class InboxScreenPayload(BaseModel):
    job_role: str
    job_details: str = ""
    job_id: str = ""
    skills_weight: float = 40
    experience_weight: float = 40
    education_weight: float = 20


@app.post("/api/inbox/screen")
def screen_inbox(payload: InboxScreenPayload, session: RecruiterSession = Depends(_session)):
    if not inbox_is_configured():
        raise HTTPException(503, "Resume inbox is not configured")
    resumes, error = fetch_new_resumes()
    if error:
        raise HTTPException(502, error)
    results = _screen_payloads([(item["filename"], item["data"]) for item in resumes], payload.job_role,
                               payload.job_details, payload.job_id,
                               {"skills_match": payload.skills_weight, "experience_fit": payload.experience_weight,
                                "education_fit": payload.education_weight}, session, "Email Inbox")
    return {"found": len(resumes), "processed": len(results), "candidates": results}


def _linkedin_redirect(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}/api/linkedin/callback"


@app.get("/api/linkedin/connect")
def linkedin_connect(request: Request, session: RecruiterSession = Depends(_session)):
    client_id = str(CONFIG.get("LINKEDIN_CLIENT_ID") or "")
    if not client_id or not CONFIG.get("LINKEDIN_CLIENT_SECRET"):
        raise HTTPException(503, "LinkedIn credentials are not configured")
    state = secrets.token_urlsafe(28)
    _linkedin_states[state] = (str(session.company["id"]), time.time() + 600)
    query = urlencode({"response_type": "code", "client_id": client_id, "redirect_uri": _linkedin_redirect(request),
                       "scope": "openid profile w_member_social", "state": state})
    return RedirectResponse(f"https://www.linkedin.com/oauth/v2/authorization?{query}")


@app.get("/api/linkedin/callback")
def linkedin_callback(request: Request, code: str, state: str, session: RecruiterSession = Depends(_session)):
    saved = _linkedin_states.pop(state, None)
    if not saved or saved[1] < time.time() or saved[0] != str(session.company["id"]):
        raise HTTPException(400, "LinkedIn connection expired or did not match this company")
    response = requests.post("https://www.linkedin.com/oauth/v2/accessToken", data={"grant_type": "authorization_code",
        "code": code, "redirect_uri": _linkedin_redirect(request), "client_id": CONFIG.get("LINKEDIN_CLIENT_ID"),
        "client_secret": CONFIG.get("LINKEDIN_CLIENT_SECRET")}, timeout=20)
    if not response.ok:
        raise HTTPException(502, "LinkedIn did not authorize this connection")
    token_data = response.json(); token = token_data.get("access_token")
    identity = requests.get("https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if not identity.ok or not identity.json().get("sub"):
        raise HTTPException(502, "LinkedIn profile details could not be read")
    info = identity.json()
    row = {"company_id": session.company["id"], "access_token": token,
           "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + int(token_data.get("expires_in", 5184000)))),
           "member_urn": f"urn:li:person:{info['sub']}", "member_name": info.get("name") or "LinkedIn member"}
    session.client.table("linkedin_connections").upsert(row, on_conflict="company_id").execute()
    return RedirectResponse("/?recruiter=1&linkedin=connected")


@app.delete("/api/linkedin/connection")
def linkedin_disconnect(session: RecruiterSession = Depends(_session)):
    session.client.table("linkedin_connections").delete().eq("company_id", session.company["id"]).execute()
    return {"ok": True}


@app.post("/api/linkedin/jobs/{job_id}")
def linkedin_post_job(job_id: int, request: Request, session: RecruiterSession = Depends(_session)):
    jobs = (session.client.table("jobs").select("*").eq("id", job_id).eq("company_id", session.company["id"]).limit(1).execute().data or [])
    connections = (session.client.table("linkedin_connections").select("*").eq("company_id", session.company["id"]).limit(1).execute().data or [])
    if not jobs or not connections:
        raise HTTPException(400, "Connect LinkedIn before publishing this job")
    job, connection = jobs[0], connections[0]
    apply_url = f"{str(request.base_url).rstrip('/')}?apply={job_id}"
    commentary = f"We're hiring: {job.get('title')}\n\n{job.get('description') or job.get('responsibilities') or ''}\n\nApply here: {apply_url}"
    payload = {"author": connection["member_urn"], "lifecycleState": "PUBLISHED", "specificContent": {
        "com.linkedin.ugc.ShareContent": {"shareCommentary": {"text": commentary}, "shareMediaCategory": "ARTICLE",
        "media": [{"status": "READY", "originalUrl": apply_url, "title": {"text": job.get("title")}}]}},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}}
    response = requests.post("https://api.linkedin.com/v2/ugcPosts", json=payload, headers={"Authorization": f"Bearer {connection['access_token']}",
        "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}, timeout=20)
    if not response.ok:
        raise HTTPException(response.status_code if response.status_code in {401, 403} else 502, "LinkedIn publishing failed; reconnect and try again")
    return {"ok": True, "message": "Job posted to LinkedIn"}


@app.get("/")
@app.get("/{path:path}")
def index(path: str = ""):
    version = str(CONFIG.get("RENDER_GIT_COMMIT") or CONFIG.get("ASSET_VERSION") or int(time.time()))[:12]
    html = (WEB / "index.html").read_text(encoding="utf-8").replace("__ASSET_VERSION__", version)
    status_code = 200 if path in {"", "index.html"} else 404
    return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-store, max-age=0"})
