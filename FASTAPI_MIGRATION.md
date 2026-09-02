# Fast web application migration

The replacement application lives in `web_app.py` and `web/`. It is kept
beside the current Streamlit application until the remaining workflows reach
feature parity and have been tested with the production Supabase project.

## Run locally

```text
python -m uvicorn web_app:app --host 0.0.0.0 --port 8765
```

## Completed in the migration shell

- Recruiter organization and access-code login
- Per-browser, per-company authenticated Supabase sessions
- One bootstrap request for jobs, candidates, interviews, and dashboard totals
- Client-side navigation without Python reruns
- Dashboard, jobs, resume screening, candidates, shortlist, interviews, and reports views
- Candidate select/reject decisions
- Parallel PDF/DOCX extraction and AI screening

## Required before replacing the production start command

- Candidate email OTP, job application, and application-status flows
- Full job create/edit/publish interface
- Interview scheduling and question generation
- Applied-candidate resume download and ZIP handoff
- AI Insights chat
- Offer-letter PDF generation and email sending
- LinkedIn OAuth callback and posting
- Production session storage (Redis or database) instead of process memory
- Browser tests against the production Supabase RLS policies

Do not change `render_start.sh` until these items pass. The current Streamlit
deployment remains the rollback-safe production application.
