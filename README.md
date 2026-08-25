# Intelligent Candidate Discovery Platform

AI-powered resume screening and candidate ranking, built with Streamlit and Google Gemini.

## Features
- Upload multiple resumes (PDF/DOCX)
- Paste a job description
- AI parses each resume into a structured profile (skills, experience, education)
- AI scores each candidate against the JD (0-100, with a breakdown by skills/experience/education)
- Ranked candidate dashboard with matched skills, gaps, and recruiter-style summaries
- AI-generated, candidate-specific interview questions

## 1. Get free API keys

**Groq (primary — recommended, 30 requests/min free)**
1. Go to https://console.groq.com
2. Sign in with Google/GitHub/email
3. Go to **API Keys** → **Create API Key**
4. Copy the key — no credit card needed

**Gemini (automatic fallback — optional but recommended)**
1. Go to https://aistudio.google.com
2. Sign in with your Google account
3. Click **Get API key** → **Create API key**
4. Copy the key

You only need one to run the app, but having both means the app automatically
switches to Gemini if Groq is ever rate-limited or down — no code changes needed.

## 2. Local setup

```bash
cd icd_app
pip install -r requirements.txt
```

Create your secrets file:
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
Open `.streamlit/secrets.toml` and paste your key(s):
```toml
GROQ_API_KEY = "your-groq-key-here"
GEMINI_API_KEY = "your-gemini-key-here"
```

Run the app:
```bash
streamlit run app.py
```

## 3. Deploy for free on Render

This project is configured for Render and includes a `Dockerfile`, `render_start.sh`,
and `render.yaml`.

1. Push this folder to a GitHub repository.
2. In Render, create a **New → Web Service** and connect the GitHub repository.
3. Choose the `main` branch.
4. Render will detect the `Dockerfile`.
5. Keep the service on the **Free** plan for a demo.
6. Add your secrets in Render:
   - Open the service → **Environment**
   - Under **Secret Files**, add a file named `secrets.toml`
   - Paste your local `.streamlit/secrets.toml` contents there
   - Do not commit the real secrets file to GitHub
7. Deploy the service.

The included `render_start.sh` copies Render's secret file into
`.streamlit/secrets.toml` at runtime, so the existing `st.secrets[...]` code
continues to work. The app listens on Render's `$PORT` automatically.

The Docker image also installs Tesseract OCR, which is required for image/scanned
resume extraction.

For integrations that use environment variables, the application already falls
back from `st.secrets` to `os.environ`.
## File structure
```
icd_app/
├── app.py              # Streamlit UI — 3 pages: Upload & Screen, Dashboard, Interview Prep
├── resume_parser.py    # PDF/DOCX text extraction
├── ai_engine.py         # Gemini API calls: parsing, scoring, interview questions
├── requirements.txt
└── .streamlit/
    └── secrets.toml.example
```

## Notes
- Scanned/image-only PDFs won't extract text (no OCR yet) — use text-based resumes for now.
- Gemini's free tier has daily rate limits; if you hit them, wait a bit or upgrade to a paid tier.
