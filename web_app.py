"""Fast ICD web application.

This is the migration target for the Streamlit UI.  It deliberately lives
beside app.py until feature parity has been verified.  The API keeps a
separate authenticated Supabase client per browser session so company RLS
tokens are never shared between recruiters.
"""

from __future__ import annotations

import json
import base64
import os
import secrets
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from supabase import Client, create_client

from ai_engine import check_api_key, parse_and_score
from resume_parser import assess_extraction_confidence, extract_text_from_bytes, heuristic_resume_check

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


def _candidate_session(icd_candidate_session: str | None = Cookie(default=None)) -> CandidateSession:
    if not icd_candidate_session:
        raise HTTPException(401, "Candidate login required")
    with _sessions_lock:
        session = _candidate_sessions.get(icd_candidate_session)
        if not session or time.monotonic() - session.last_seen > SESSION_TTL:
            _candidate_sessions.pop(icd_candidate_session, None)
            raise HTTPException(401, "Candidate session expired")
        session.last_seen = time.monotonic()
        return session


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


@app.get("/api/health")
def health():
    return {"ok": True, "service": "icd-web"}


@app.get("/api/organizations")
def organizations(search: str = ""):
    query = _public_client().table("companies_public").select("*").order("name")
    if search.strip():
        query = query.ilike("name", f"%{search.strip()}%")
    return query.limit(50).execute().data or []


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
    response.set_cookie("icd_candidate_session", session_id, httponly=True,
                        secure=bool(CONFIG.get("RENDER")),
                        samesite="lax", max_age=SESSION_TTL)
    return {"ok": True}


@app.delete("/api/candidate/session")
def candidate_logout(response: Response, icd_candidate_session: str | None = Cookie(default=None)):
    if icd_candidate_session:
        with _sessions_lock:
            _candidate_sessions.pop(icd_candidate_session, None)
    response.delete_cookie("icd_candidate_session")
    return {"ok": True}


@app.get("/api/candidate/me")
def candidate_me(session: CandidateSession = Depends(_candidate_session)):
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
    parsed = [_candidate(row) for row in candidates]
    return {
        "company": session.company,
        "jobs": jobs,
        "candidates": parsed,
        "interviews": interviews,
        "summary": {
            "active_jobs": sum(job.get("status") == "active" for job in jobs),
            "candidates": len(parsed),
            "shortlisted": sum(candidate["score"] >= 70 for candidate in parsed),
            "selected": sum(candidate.get("decision_status") == "Selected" for candidate in parsed),
            "scheduled_interviews": sum(item.get("status") == "Scheduled" for item in interviews),
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


@app.post("/api/jobs")
def create_job(payload: JobPayload, session: RecruiterSession = Depends(_session)):
    row = {**payload.model_dump(), "company_id": session.company["id"], "status": "active"}
    result = session.client.table("jobs").insert(row).execute().data or []
    if not result:
        raise HTTPException(500, "The job could not be saved")
    return result[0]


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    result = (session.client.table("jobs").update(payload).eq("id", job_id)
              .eq("company_id", session.company["id"]).execute().data or [])
    return result[0] if result else {"ok": True}


@app.patch("/api/candidates/{candidate_id}")
def update_candidate(candidate_id: int, payload: dict[str, Any], session: RecruiterSession = Depends(_session)):
    allowed = {
        ("decision_status" if key == "status" else key): value
        for key, value in payload.items() if key in {"status", "notes", "interview_score"}
    }
    if not allowed:
        raise HTTPException(400, "No supported fields were supplied")
    result = (session.client.table("screening_history").update(allowed).eq("id", candidate_id)
              .eq("company_id", session.company["id"]).execute().data or [])
    return _candidate(result[0]) if result else {"ok": True}


@app.post("/api/screen")
async def screen_resumes(
    job_role: str = Form(...), job_details: str = Form(""), job_id: str = Form(""),
    files: list[UploadFile] = File(...), session: RecruiterSession = Depends(_session),
):
    if not check_api_key():
        raise HTTPException(503, "No AI provider is configured")
    payloads = [(file.filename or "resume.pdf", await file.read()) for file in files]
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
                "status": "active", "decision_status": "Waiting", "source": "Web Upload",
            }
            saved = session.client.table("screening_history").insert(row).execute().data or []
            results.append(_candidate(saved[0] if saved else row))
    return {"processed": len(results), "candidates": sorted(results, key=lambda item: item["score"], reverse=True)}


@app.get("/")
@app.get("/{path:path}")
def index(path: str = ""):
    return FileResponse(WEB / "index.html")
