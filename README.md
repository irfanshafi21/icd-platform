<div align="center">

<img src="https://readme-typing-svg.demolab.com?font=Poppins&size=32&duration=3000&pause=1000&color=185FA5&center=true&vCenter=true&width=700&lines=Intelligent+Candidate+Discovery;AI-Powered+Resume+Screening;From+Resume+to+Shortlist+in+Seconds" alt="Typing SVG" />

<br/>

[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Supabase](https://img.shields.io/badge/Database-Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)](https://supabase.com)
[![Groq](https://img.shields.io/badge/LLM-Groq-F55036?style=for-the-badge)](https://groq.com)
[![Cerebras](https://img.shields.io/badge/LLM-Cerebras-6C4FF6?style=for-the-badge)](https://cerebras.ai)
[![Gemini](https://img.shields.io/badge/Fallback-Gemini-4285F4?style=for-the-badge&logo=googlegemini&logoColor=white)](https://aistudio.google.com)
[![Docker](https://img.shields.io/badge/Deploy-Docker%20%2B%20Render-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://render.com)

<br/>

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Status](https://img.shields.io/badge/Status-Active-success?style=flat-square)
![Multi--Tenant](https://img.shields.io/badge/Architecture-Multi--Tenant-185FA5?style=flat-square)
![License](https://img.shields.io/badge/License-Unspecified-lightgrey?style=flat-square)

<br/>

### 🧠 AI-powered, multi-tenant recruitment automation
**Resume parsing → LLM scoring → ranked, explainable shortlist — end to end.**

</div>

<br/>

<div align="center">

```
┌──────────────────────────────────────────────────────────────────┐
│   📄 Resumes In   →   🤖 AI Screening   →   🏆 Ranked Shortlist    │
└──────────────────────────────────────────────────────────────────┘
```

</div>

<br/>

> [!NOTE]
> Every company operates as an **isolated tenant** behind a single 4-digit access code. No passwords. No visible accounts. Just a code.

<br/>

---

<br/>

## ✨ Features

<table>
<tr>
<td width="33%" valign="top">

### 🔍 Screening & Ranking

```diff
+ Bulk upload — PDF / DOCX / ZIP
+ AI-structured candidate profiles
+ 0–100 explainable AI scoring
+ Duplicate detection via hashing
+ Free local ATS heuristics
+ Ranked dashboard + gap analysis
+ AI interview question generation
+ Prompt-grounded chat assistant
```

</td>
<td width="33%" valign="top">

### 📥 Sourcing

```diff
+ No-login public apply portal
+ QR-code apply flow
+ Self-serve OTP status check
+ IMAP inbox auto-intake
+ LinkedIn feed job-posting
```

</td>
<td width="33%" valign="top">

### 🏢 Tenancy & Reports

```diff
+ Company-scoped Supabase RLS
+ Passwordless access-code login
+ PDF / Excel / CSV reports
+ Offer letter generation
+ Cross-session analytics
+ Browser voice assistant
```

</td>
</tr>
</table>

<br/>

---

<br/>

## 🏗️ Architecture

<div align="center">

| 🧩 Layer | ⚡ Technology |
|:---|:---|
| **UI** | Streamlit — page-routed via session state |
| **LLM Providers** | 🟠 Groq + 🟣 Cerebras (primary, load-balanced) → 🔵 Gemini (fallback) |
| **Database / Auth** | 🟢 Supabase — Postgres + Row Level Security |
| **Resume Parsing** | pypdf, python-docx |
| **Reports** | ReportLab (PDF) · openpyxl + pandas (Excel/CSV) |
| **Email** | SMTP or Google Apps Script — branded HTML |
| **Deployment** | 🐳 Docker on Render |

</div>

<br/>

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#DBEAFE','primaryBorderColor':'#3B82F6','lineColor':'#185FA5','fontSize':'14px'}}}%%
flowchart TB
    subgraph Sourcing["📥  SOURCING CHANNELS"]
        direction LR
        A1["🖱️ Manual Upload"]
        A2["🔗 Public Portal / QR"]
        A3["📧 Email Inbox (IMAP)"]
    end

    subgraph Core["⚙️  CORE PIPELINE"]
        direction LR
        B1["📄 resume_parser.py<br/>extract + heuristics"]
        B2["🤖 ai_engine.py<br/>parse · score · ATS"]
        B3["🗄️ db.py<br/>Supabase · RLS"]
    end

    subgraph App["📊  APPLICATION LAYER"]
        direction LR
        C1["🏠 app.py<br/>Dashboard · Ranking · Chat"]
        C2["🎤 Interview Prep"]
        C3["📑 reports.py<br/>PDF · Excel · CSV"]
    end

    subgraph Out["📤  OUTBOUND"]
        direction LR
        D1["✉️ email_utils.py"]
        D2["💼 linkedin_integration.py"]
    end

    A1 --> B1
    A2 --> B1
    A3 --> B1
    B1 --> B2 --> B3 --> C1
    C1 --> C2
    C1 --> C3
    C1 -.-> D1
    C1 -.-> D2

    style Sourcing fill:#DBEAFE,stroke:#3B82F6,stroke-width:2px
    style Core fill:#DCFCE7,stroke:#22C55E,stroke-width:2px
    style App fill:#F1F5F9,stroke:#185FA5,stroke-width:2px
    style Out fill:#FEF3E2,stroke:#F59E0B,stroke-width:2px
```

<br/>

---

<br/>

## 🔄 Core Workflow

<table>
<tr><td width="70px" align="center"><h2>1️⃣</h2></td><td>

### Company Login — `auth.py`
A company signs up once and gets a **4-digit access code**. Behind the scenes, `create_company()` provisions a hidden, auto-generated Supabase Auth account so Row-Level-Security can scope every query per company — the human never sees a password.

</td></tr>

<tr><td align="center"><h2>2️⃣</h2></td><td>

### Sourcing — three channels feed one pipeline

| Channel | Module | Entry Point |
|:---|:---|:---|
| 🖱️ Manual upload | `app.py` | recruiter drags in files |
| 🔗 Public apply link / QR | `public_portal.py` | `render_apply_page()` + OTP |
| 📧 Inbox auto-intake | `inbox_intake.py` | `fetch_new_resumes()` (IMAP) |

</td></tr>

<tr><td align="center"><h2>3️⃣</h2></td><td>

### Parsing — `resume_parser.py`
`extract_text_from_bytes()` → `heuristic_resume_check()` *(filters junk, free)* → `compute_local_ats_metrics()` *(baseline ATS score, free)* — all **before** a single paid API call is made.

</td></tr>

<tr><td align="center"><h2>4️⃣</h2></td><td>

### AI Scoring — `ai_engine.py`
`parse_and_score()` orchestrates:

```
parse_resume_with_ai()  →  score_candidate()  →  analyze_ats_ai()
```

Every call is wrapped in retry logic, rate limiting, and **quota-aware key rotation** (`_KeyPool`) — a provider hitting its daily limit never stops the pipeline.

</td></tr>

<tr><td align="center"><h2>5️⃣</h2></td><td>

### Dedup + Concurrency — `app.py`
Resumes are content-hashed to skip re-screening. A `ThreadPoolExecutor` *(capped at 5 workers)* scores multiple candidates in parallel without tripping provider rate limits.

</td></tr>

<tr><td align="center"><h2>6️⃣</h2></td><td>

### Ranking & Review — `db.py` + `app.py`
`save_screening_record()` persists results; `smart_rank_key()` ranks the pool. A **prompt-grounded chat assistant** (`ask_assistant()`) lets recruiters query the live candidate list — no vector DB, no RAG.

</td></tr>

<tr><td align="center"><h2>7️⃣</h2></td><td>

### Interview Prep
`generate_interview_questions()` builds candidate-specific questions from their profile, score, and the JD. Interviews are tracked independently via `create_interview()`.

</td></tr>

<tr><td align="center"><h2>8️⃣</h2></td><td>

### Reports & Notify — `reports.py` + `email_utils.py`
Candidate reports, shortlists, and offer letters export as branded PDF/Excel/CSV. OTPs and notifications go out via SMTP or Google Apps Script.

</td></tr>
</table>

<br/>

```mermaid
%%{init: {'theme':'base', 'themeVariables': {'primaryColor':'#DCFCE7','primaryBorderColor':'#22C55E','lineColor':'#185FA5'}}}%%
sequenceDiagram
    autonumber
    participant 🧑 as Candidate
    participant Portal as public_portal.py
    participant Parser as resume_parser.py
    participant AI as ai_engine.py
    participant DB as db.py (Supabase)
    participant 👤 as Recruiter
    participant Reports as reports.py

    🧑->>Portal: Apply (resume + OTP)
    Portal->>Parser: raw file bytes
    Parser->>Parser: extract_text_from_bytes()
    Parser->>Parser: heuristic_resume_check()
    Parser->>AI: cleaned resume text
    AI->>AI: parse_resume_with_ai()
    AI->>AI: score_candidate()
    AI->>DB: save_screening_record()
    👤->>DB: fetch_screening_history()
    DB-->>👤: ranked candidate list
    👤->>AI: generate_interview_questions()
    👤->>Reports: build_shortlist_report_pdf()
    Reports-->>👤: 📄 downloadable PDF / Excel
```

<br/>

---

<br/>

## 🎨 Design System

<div align="center">

*One source of truth — `components.py` — powers every page's colors, chips, and buttons.*

</div>

<br/>

### 🎨 Color Palette

<table>
<tr><th>Swatch</th><th>Token</th><th>Hex</th><th>Used For</th></tr>
<tr><td>![#185FA5](https://img.shields.io/badge/-%20-185FA5?style=flat-square)</td><td><code>primary</code></td><td><code>#185FA5</code></td><td>Primary actions, headers, brand accents</td></tr>
<tr><td>![#5FA8FF](https://img.shields.io/badge/-%20-5FA8FF?style=flat-square)</td><td><code>primary_light</code></td><td><code>#5FA8FF</code></td><td>Hover states, secondary highlights</td></tr>
<tr><td>![#22C55E](https://img.shields.io/badge/-%20-22C55E?style=flat-square)</td><td><code>success</code></td><td><code>#22C55E</code></td><td>Selected · Completed · Active · Strong Fit</td></tr>
<tr><td>![#DCFCE7](https://img.shields.io/badge/-%20-DCFCE7?style=flat-square)</td><td><code>success_bg</code></td><td><code>#DCFCE7</code></td><td>Success chip/badge background</td></tr>
<tr><td>![#F59E0B](https://img.shields.io/badge/-%20-F59E0B?style=flat-square)</td><td><code>warning</code></td><td><code>#F59E0B</code></td><td>Waiting · Pending · Good Fit</td></tr>
<tr><td>![#FEF3E2](https://img.shields.io/badge/-%20-FEF3E2?style=flat-square)</td><td><code>warning_bg</code></td><td><code>#FEF3E2</code></td><td>Warning chip/badge background</td></tr>
<tr><td>![#EF4444](https://img.shields.io/badge/-%20-EF4444?style=flat-square)</td><td><code>danger</code></td><td><code>#EF4444</code></td><td>Rejected · Cancelled · Weak Fit</td></tr>
<tr><td>![#FEE2E2](https://img.shields.io/badge/-%20-FEE2E2?style=flat-square)</td><td><code>danger_bg</code></td><td><code>#FEE2E2</code></td><td>Danger chip/badge background</td></tr>
<tr><td>![#3B82F6](https://img.shields.io/badge/-%20-3B82F6?style=flat-square)</td><td><code>info</code></td><td><code>#3B82F6</code></td><td>Scheduled · informational states</td></tr>
<tr><td>![#DBEAFE](https://img.shields.io/badge/-%20-DBEAFE?style=flat-square)</td><td><code>info_bg</code></td><td><code>#DBEAFE</code></td><td>Info chip/badge background</td></tr>
<tr><td>![#F1F5F9](https://img.shields.io/badge/-%20-F1F5F9?style=flat-square)</td><td><code>neutral_bg</code></td><td><code>#F1F5F9</code></td><td>Neutral surfaces, Archived state</td></tr>
<tr><td>![#3E484F](https://img.shields.io/badge/-%20-3E484F?style=flat-square)</td><td><code>neutral_text</code></td><td><code>#3E484F</code></td><td>Body text on neutral surfaces</td></tr>
</table>

<br/>

### 🏷️ Status → Color Mapping

<div align="center">

| Status Group | Color | Labels |
|:---:|:---:|:---|
| 🟢 | **Success** | Selected · Completed · Active · Strong Fit |
| 🔴 | **Danger** | Rejected · Cancelled · Weak Fit |
| 🔵 | **Info** | Scheduled |
| 🟠 | **Warning** | Good Fit · Waiting |
| ⚪ | **Neutral** | Pending · Archived |

</div>

> [!TIP]
> Defined once in `STATUS_VARIANTS` — the same label renders **identically** on every page, every time. No drift, no duplicated color logic.

<br/>

### 🧩 UI Conventions

<table>
<tr><td>🔘 <b>Buttons</b></td><td>8px rounded corners · scale-down on click · visible focus ring <code>#378ADD</code></td></tr>
<tr><td>💊 <b>Status Chips</b></td><td>Consistent pill shape, colored via <code>STATUS_VARIANTS</code></td></tr>
<tr><td>📊 <b>Stat Cards</b></td><td>Icon + label + value + optional subtext, <code>primary</code> accent by default</td></tr>
<tr><td>🧱 <b>Markup</b></td><td>Zero raw inline HTML/CSS duplication — everything routes through <code>components.py</code></td></tr>
</table>

<br/>

---

<br/>

## 🗂️ Module Map

<table>
<tr><th>Module</th><th>Responsibility</th></tr>
<tr><td>🏠&nbsp;<code>app.py</code></td><td>UI shell — Screening, Dashboard, Interview Prep, Jobs, Reports, Auth gate</td></tr>
<tr><td>🤖&nbsp;<code>ai_engine.py</code></td><td>All LLM calls — parsing, scoring, ATS analysis, interview Qs, chat assistant</td></tr>
<tr><td>📄&nbsp;<code>resume_parser.py</code></td><td>PDF/DOCX/ZIP text extraction, local (non-AI) heuristics & ATS metrics</td></tr>
<tr><td>🔐&nbsp;<code>auth.py</code></td><td>Access-code login; per-company hidden Supabase Auth accounts</td></tr>
<tr><td>🗄️&nbsp;<code>db.py</code></td><td>Supabase persistence — jobs, candidates, interviews, applications, LinkedIn tokens</td></tr>
<tr><td>🎨&nbsp;<code>components.py</code></td><td>Shared UI — design tokens, buttons, chips, stat cards, info panels</td></tr>
<tr><td>📑&nbsp;<code>reports.py</code></td><td>PDF/Excel/CSV generation — candidate reports, shortlists, interviews, offer letters</td></tr>
<tr><td>🔗&nbsp;<code>public_portal.py</code></td><td>No-login candidate pages — apply to a job, check status via OTP</td></tr>
<tr><td>📧&nbsp;<code>inbox_intake.py</code></td><td>IMAP polling — pulls resumes from a dedicated inbox into the pipeline</td></tr>
<tr><td>💼&nbsp;<code>linkedin_integration.py</code></td><td>LinkedIn OAuth + posting a job opening to a connected personal feed</td></tr>
<tr><td>🎤&nbsp;<code>icd_voice.py</code></td><td>Browser voice assistant — spoken commands mapped to in-app actions</td></tr>
<tr><td>✉️&nbsp;<code>email_utils.py</code></td><td>Outbound email — OTP codes, branded HTML, PDF attachments</td></tr>
<tr><td>⚙️&nbsp;<code>local_settings.py</code></td><td>Local (non-secret) app settings persistence</td></tr>
</table>

<br/>

---

<br/>

## 🚀 Getting Started

### 1️⃣ Get free API keys

<table>
<tr><td>🟠&nbsp;<b>Groq</b><br/><sub>primary — 30 req/min free</sub></td><td>👉 <a href="https://console.groq.com">console.groq.com</a> → API Keys → Create API Key</td></tr>
<tr><td>🟣&nbsp;<b>Cerebras</b><br/><sub>primary — free tier</sub></td><td>👉 <a href="https://cloud.cerebras.ai">cloud.cerebras.ai</a> → create an API key</td></tr>
<tr><td>🔵&nbsp;<b>Gemini</b><br/><sub>fallback</sub></td><td>👉 <a href="https://aistudio.google.com">aistudio.google.com</a> → Get API key</td></tr>
</table>

> [!TIP]
> Only **one** key is required to run the app — configuring more enables automatic failover and quota rotation (`GROQ_API_KEY_2`, `GROQ_API_KEY_3`, ...).

### 2️⃣ Local setup

```bash
git clone https://github.com/irfanshafi21/icd-platform.git
cd icd-platform
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml`:

```toml
GROQ_API_KEY = "your-groq-key"
CEREBRAS_API_KEY = "your-cerebras-key"
GEMINI_API_KEY = "your-gemini-key"

SUPABASE_URL = "your-supabase-url"
SUPABASE_KEY = "your-supabase-service-key"
```

### 3️⃣ Run it

```bash
streamlit run app.py
```

<br/>

---

<br/>

## ☁️ Deployment

<div align="center">

**Repo ships with `Dockerfile` · `render_start.sh` · `render.yaml` — Render-ready out of the box**

</div>

<table>
<tr><td align="center">1</td><td>Push to GitHub → in Render: <b>New → Web Service</b> → connect the repo, branch <code>main</code></td></tr>
<tr><td align="center">2</td><td>Render auto-detects the <code>Dockerfile</code> — Free plan is fine for a demo</td></tr>
<tr><td align="center">3</td><td>Under <b>Environment → Secret Files</b>, add a file named <code>secrets.toml</code> with your local secrets</td></tr>
<tr><td align="center">4</td><td>Deploy — <code>render_start.sh</code> copies the secret file into place at runtime; app listens on Render's <code>$PORT</code> automatically</td></tr>
</table>

> [!IMPORTANT]
> Never commit real secrets to GitHub. Environment-variable integrations also work — `st.secrets` falls back to `os.environ` automatically.

<br/>

---

<br/>

## ⚠️ Known Constraints

<table>
<tr><td>🖼️</td><td><b>No OCR</b></td><td>Text-based PDF/DOCX only — Tesseract removed to keep Render startup fast</td></tr>
<tr><td>🧵</td><td><b>Concurrency cap</b></td><td>Screening capped at 5 parallel workers to avoid provider throttling</td></tr>
<tr><td>🔁</td><td><b>Dedup</b></td><td>Identical-hash files already screened for a job are skipped, not re-billed</td></tr>
<tr><td>⏳</td><td><b>Gemini limits</b></td><td>Free tier has daily rate limits</td></tr>
<tr><td>💬</td><td><b>No RAG</b></td><td>Chat assistant is prompt-grounded on the live candidate pool only</td></tr>
<tr><td>💼</td><td><b>LinkedIn scope</b></td><td>Posts to a personal feed only — not the LinkedIn Jobs board</td></tr>
</table>

<br/>

---

<br/>

## 📄 License

No license specified yet — add one (**MIT** / **Apache-2.0** are common choices for academic or open projects) before sharing widely.

<br/>

<div align="center">

<br/>

**Built by Mohamed Irfan Shafi using Streamlit, Supabase, and free-tier LLMs**

![Made with Python](https://img.shields.io/badge/Made%20with-Python-1f425f.svg?style=flat-square)
![Maintained](https://img.shields.io/badge/Maintained%3F-yes-green.svg?style=flat-square)

</div>
