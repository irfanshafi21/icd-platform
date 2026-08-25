"""
Report generation — Candidate, Shortlist, Interview, and Hiring reports,
exportable as PDF, Excel, or CSV. All functions operate on real data passed
in (candidates already screened, interviews already scheduled) — nothing
here fabricates figures.
"""

import io
import os
import pandas as pd
from xml.sax.saxutils import escape as _xesc
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader

_LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo_header.png")
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")

# Signature style options for the offer letter — each maps to an OFL-licensed
# handwriting font bundled in assets/fonts. Registered once at import time;
# any font whose file is missing is silently skipped rather than crashing.
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

SIGNATURE_STYLES = {
    "Elegant Script": "GreatVibes",
    "Flowing Cursive": "AlexBrush",
    "Casual Handwriting": "Sacramento",
    "Rounded Script": "DancingScript",
    "Bold Brush": "Pacifico",
}

for _style_name, _font_name in SIGNATURE_STYLES.items():
    _font_path = os.path.join(_FONTS_DIR, f"{_font_name}.ttf")
    if os.path.exists(_font_path):
        try:
            pdfmetrics.registerFont(TTFont(_font_name, _font_path))
        except Exception:
            pass


# ----------------------------- DataFrame builders -----------------------------

def candidates_to_dataframe(candidates: list[dict]) -> pd.DataFrame:
    rows = []
    for c in candidates:
        if c["score"].get("error"):
            continue
        p, s = c["profile"], c["score"]
        b = s.get("breakdown", {})
        rows.append({
            "Name": c["name"],
            "Overall Score": s.get("overall_score"),
            "Skills Match": b.get("skills_match"),
            "Experience Fit": b.get("experience_fit"),
            "Education Fit": b.get("education_fit"),
            "Years Experience": p.get("years_experience"),
            "Education": p.get("education"),
            "Matched Skills": ", ".join(s.get("matched_skills", [])),
            "Gaps": ", ".join(s.get("gaps", [])),
            "Email": p.get("email"),
            "Phone": p.get("phone"),
        })
    return pd.DataFrame(rows)


def interviews_to_dataframe(interviews: list[dict]) -> pd.DataFrame:
    rows = []
    for i in interviews:
        rows.append({
            "Candidate": i.get("candidate_name"),
            "Job Role": i.get("job_role"),
            "Type": i.get("interview_type"),
            "Scheduled At": i.get("scheduled_at"),
            "Status": i.get("status"),
            "Interview Score": i.get("interview_score") if i.get("status") == "Completed" else None,
            "Notes": i.get("notes"),
        })
    return pd.DataFrame(rows)


# ----------------------------- Export helpers -----------------------------

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()


# ----------------------------- PDF reports -----------------------------

def _pdf_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("RTitle", parent=styles["Heading1"], fontSize=18, spaceAfter=6, textColor=colors.HexColor("#00506B")),
        "sub": ParagraphStyle("RSub", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#64748B"), spaceAfter=14),
        "h2": ParagraphStyle("RH2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#00506B")),
        "body": ParagraphStyle("RBody", parent=styles["Normal"], fontSize=10.5, leading=15),
    }


def _pdf_header(report_title: str, subtitle: str) -> list:
    """Branded header used at the top of every PDF report: logo + app name
    on the left, report title/subtitle below. Falls back to text-only if
    the logo asset isn't found, so report generation never breaks."""
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle("HdrName", parent=styles["Normal"], fontSize=15, leading=17,
                                 textColor=colors.HexColor("#0B1C30"), fontName="Helvetica-Bold")
    tagline_style = ParagraphStyle("HdrTag", parent=styles["Normal"], fontSize=7.5, leading=9,
                                    textColor=colors.HexColor("#00506B"), fontName="Helvetica-Bold")

    brand_cell = [
        Paragraph('<font color="#00506B">ICD</font> Platform', name_style),
        Paragraph("INTELLIGENT CANDIDATE DISCOVERY PLATFORM", tagline_style),
    ]

    if os.path.exists(_LOGO_PATH):
        logo = Image(_LOGO_PATH, width=0.62*inch, height=0.34*inch)
        header_table = Table([[logo, brand_cell]], colWidths=[0.75*inch, 5.9*inch])
    else:
        header_table = Table([[brand_cell]], colWidths=[6.65*inch])

    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))

    return [
        header_table,
        Spacer(1, 4),
        Table([[""]], colWidths=[6.65*inch], style=TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#E2E8F0"))])),
        Spacer(1, 10),
        Paragraph(report_title, ParagraphStyle("RTitle3", parent=getSampleStyleSheet()["Heading1"],
                                                fontSize=17, spaceAfter=4, textColor=colors.HexColor("#00506B"))),
        Paragraph(subtitle, ParagraphStyle("RSub3", parent=getSampleStyleSheet()["Normal"],
                                            fontSize=10, textColor=colors.HexColor("#64748B"), spaceAfter=12)),
    ]


def _job_details_block(job_role: str = None, job_details: str = None, key_skills: list | None = None,
                        weights: dict | None = None, note: str | None = None) -> list:
    """A consistent 'Job Details & Scoring Weights' section reused across all
    three report types. Skips entirely if there's nothing real to show, so it
    never fabricates a job that wasn't actually configured."""
    if not (job_role or job_details or key_skills or weights):
        return []

    body_style = ParagraphStyle("JobBody", parent=getSampleStyleSheet()["Normal"], fontSize=10, leading=14)
    flow = [
        Paragraph("Job Details &amp; Scoring Weights", ParagraphStyle(
            "H2Job", parent=getSampleStyleSheet()["Heading2"], fontSize=13,
            spaceBefore=6, spaceAfter=6, textColor=colors.HexColor("#00506B"))),
    ]
    if note:
        flow.append(Paragraph(f"<i>{_xesc(note)}</i>", ParagraphStyle(
            "JobNote", parent=body_style, fontSize=8.5, textColor=colors.HexColor("#94A3B8"))))
    flow.append(Paragraph(f"<b>Job Title:</b> {_xesc(job_role) if job_role else '—'}", body_style))
    if job_details:
        desc = job_details.strip()
        if len(desc) > 500:
            desc = desc[:500].rsplit(" ", 1)[0] + "…"
        flow.append(Paragraph(f"<b>Description:</b> {_xesc(desc)}", body_style))
    if key_skills:
        flow.append(Paragraph(f"<b>Key Skills:</b> {_xesc(', '.join(key_skills))}", body_style))
    w = weights or {"skills": 40, "experience": 40, "education": 20}
    flow.append(Paragraph(
        f"<b>Scoring Weights:</b> Skills {w.get('skills', 40)}% &nbsp;·&nbsp; "
        f"Experience {w.get('experience', 40)}% &nbsp;·&nbsp; Education {w.get('education', 20)}%",
        body_style,
    ))
    flow.append(Spacer(1, 10))
    return flow


def build_candidate_report_pdf(candidate: dict, job_role: str, job_details: str = None,
                                key_skills: list | None = None, weights: dict | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch,
                             leftMargin=0.7*inch, rightMargin=0.7*inch)
    st_ = _pdf_styles()
    p, s = candidate["profile"], candidate["score"]
    b = s.get("breakdown", {})

    content = _pdf_header(f"Candidate Report — {candidate['name']}", f"Screened for: {job_role or '—'}")
    content += _job_details_block(job_role, job_details, key_skills, weights)
    content += [
        Paragraph("Overall Assessment", st_["h2"]),
        Paragraph(f"Overall Score: <b>{s.get('overall_score','—')}/100</b>", st_["body"]),
        Paragraph(f"Skills Match: {b.get('skills_match','—')}/100 &nbsp;|&nbsp; "
                   f"Experience Fit: {b.get('experience_fit','—')}/100 &nbsp;|&nbsp; "
                   f"Education Fit: {b.get('education_fit','—')}/100", st_["body"]),
        Paragraph("Recruiter Summary", st_["h2"]),
        Paragraph(s.get("summary", "—"), st_["body"]),
        Paragraph("Matched Skills", st_["h2"]),
        Paragraph(", ".join(s.get("matched_skills", [])) or "—", st_["body"]),
        Paragraph("Gaps", st_["h2"]),
        Paragraph(", ".join(s.get("gaps", [])) or "—", st_["body"]),
        Paragraph("Profile Details", st_["h2"]),
        Paragraph(f"Experience: {p.get('years_experience','—')}", st_["body"]),
        Paragraph(f"Education: {p.get('education','—')}", st_["body"]),
        Paragraph(f"Contact: {p.get('email','—')} · {p.get('phone','—')}", st_["body"]),
    ]
    doc.build(content)
    return buf.getvalue()


def _make_faded_logo(path: str, opacity: float = 0.07):
    """Returns an in-memory low-opacity version of a logo image, for use as
    a watermark. Returns None if the image can't be processed for any
    reason — a missing watermark should never break PDF generation."""
    try:
        from PIL import Image as PILImage
        img = PILImage.open(path).convert("RGBA")
        alpha = img.getchannel("A").point(lambda p: int(p * opacity))
        img.putalpha(alpha)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        return None


def build_offer_letter_pdf(candidate: dict, offer: dict, logo_path: str | None = None,
                            logo_bytes: bytes | None = None) -> bytes:
    """
    A branded job offer letter PDF for one selected candidate — letterhead,
    date, recipient block, offer paragraph, compensation, acceptance
    deadline, a real handwritten-style signature, and footer contact strip.
    Filled entirely from real data passed in via `offer` (company name/logo/
    contact, job title, location, salary, start date, reporting manager, HR
    signee + chosen signature style, acceptance deadline) — nothing here is
    fabricated. `logo_path` or `logo_bytes` overrides the app's default logo
    with a company's own logo — pass whichever you have; logo_bytes takes
    priority if both are given (used for a company's logo stored in the
    database rather than as a file on disk).
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.45*inch, bottomMargin=0.55*inch,
                             leftMargin=0.75*inch, rightMargin=0.75*inch)

    TEAL = colors.HexColor("#00506B")
    DARK = colors.HexColor("#0B1C30")
    GREY = colors.HexColor("#64748B")

    # Normalize to raw bytes once, regardless of source, so every use site
    # below (letterhead, footer, watermark) can just open a fresh BytesIO —
    # avoids the "already-consumed stream" issue of reusing one BytesIO object.
    _raw_logo_bytes = None
    if logo_bytes:
        _raw_logo_bytes = logo_bytes
    elif logo_path and os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            _raw_logo_bytes = f.read()
    elif os.path.exists(_LOGO_PATH):
        with open(_LOGO_PATH, "rb") as f:
            _raw_logo_bytes = f.read()

    def _logo_stream():
        return io.BytesIO(_raw_logo_bytes) if _raw_logo_bytes else None

    active_logo = _logo_stream()  # used for the letterhead Image() below; footer/watermark get their own fresh streams
    sig_font = SIGNATURE_STYLES.get(offer.get("signature_style", ""), None)
    sig_font_registered = sig_font in pdfmetrics.getRegisteredFontNames() if sig_font else False

    styles = getSampleStyleSheet()
    company_style = ParagraphStyle("OLCompany", parent=styles["Normal"], fontSize=13, leading=17, textColor=DARK, fontName="Helvetica-Bold")
    company_sub = ParagraphStyle("OLCompanySub", parent=styles["Normal"], fontSize=9, leading=13, textColor=GREY)
    title_style = ParagraphStyle("OLTitle", parent=styles["Heading1"], fontSize=17, textColor=DARK, alignment=2, fontName="Helvetica-Bold")
    date_style = ParagraphStyle("OLDate", parent=styles["Normal"], fontSize=10, textColor=DARK, alignment=2)
    label_bold = ParagraphStyle("OLLabelBold", parent=styles["Normal"], fontSize=10.5, leading=15, textColor=DARK, fontName="Helvetica-Bold")
    body = ParagraphStyle("OLBody", parent=styles["Normal"], fontSize=9.5, leading=13.5, textColor=DARK, spaceAfter=6)
    sign_script = ParagraphStyle("OLSignScript", parent=styles["Normal"], fontSize=28, leading=32,
                                  textColor=TEAL, fontName=(sig_font if sig_font_registered else "Helvetica-BoldOblique"))
    sign_name = ParagraphStyle("OLSignName", parent=styles["Normal"], fontSize=11, textColor=DARK, fontName="Helvetica-Bold")
    sign_role = ParagraphStyle("OLSignRole", parent=styles["Normal"], fontSize=9.5, textColor=GREY)

    summary_label = ParagraphStyle("OLSummaryLabel", parent=styles["Normal"], fontSize=9, textColor=GREY, fontName="Helvetica-Bold")
    summary_value = ParagraphStyle("OLSummaryValue", parent=styles["Normal"], fontSize=10, textColor=DARK, fontName="Helvetica-Bold")

    def _e(v):
        return _xesc(str(v)) if v is not None else ""

    # ---- Letterhead: logo + company name/tagline on the left, "JOB OFFER LETTER" on the right, a thin rule below ----
    company_cell = [Paragraph(_e(offer.get("company_name", "Our Company")), company_style)]
    if offer.get("company_tagline"):
        company_cell.append(Paragraph(_e(offer["company_tagline"]), company_sub))
    if active_logo:
        logo = Image(active_logo, width=0.55*inch, height=0.55*inch, kind="proportional")
        left_cell = Table([[logo, company_cell]], colWidths=[0.65*inch, 3.0*inch])
        left_cell.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    else:
        left_cell = Table([company_cell], colWidths=[3.65*inch])

    header_table = Table([[left_cell, Paragraph("JOB OFFER LETTER", title_style)]], colWidths=[3.9*inch, 2.85*inch])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    rule = Table([[""]], colWidths=[6.75*inch], rowHeights=[1.1])
    rule.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), DARK)]))

    content = [header_table, rule, Spacer(1, 10)]

    # ---- Company contact (left) / date (right) — no address, just name + phone/email ----
    company_contact_lines = [Paragraph(_e(offer.get("company_name", "Our Company")), label_bold)]
    for line in filter(None, [offer.get("company_phone"), offer.get("company_email")]):
        company_contact_lines.append(Paragraph(_e(line), ParagraphStyle("OLContact", parent=body, spaceAfter=2)))
    info_row = Table(
        [[company_contact_lines, Paragraph(_e(offer.get("date", "")), date_style)]],
        colWidths=[4.0*inch, 2.75*inch],
    )
    info_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    content.append(info_row)
    content.append(Spacer(1, 10))

    # ---- Recipient ----
    content.append(Paragraph("To:", body))
    content.append(Paragraph(_e(candidate.get("name", "Candidate")), label_bold))
    if candidate.get("profile", {}).get("email"):
        content.append(Paragraph(_e(candidate["profile"]["email"]), body))
    content.append(Spacer(1, 6))

    # ---- Opening ----
    content.append(Paragraph(f"Dear {_e(candidate.get('name', 'Candidate').split(' ')[0])},", body))
    content.append(Paragraph(
        f"We are pleased to offer you the position of <b>{_e(offer.get('job_title', '—'))}</b> at "
        f"<b>{_e(offer.get('company_name', 'our company'))}</b>, starting on <b>{_e(offer.get('start_date', '—'))}</b>."
        + (f" In this role, you will report to <b>{_e(offer['reporting_manager'])}</b>" if offer.get("reporting_manager") else "")
        + (f" and will be based at our <b>{_e(offer['location'])}</b> office." if offer.get("location") else "."),
        body,
    ))

    # ---- Offer summary box — quick-reference terms, salary always stated on an annual basis ----
    summary_rows = [
        ("Position", offer.get("job_title", "—")),
        ("Department", offer.get("department", "")),
        ("Employment Type", offer.get("employment_type", "Full-time")),
        ("Location", offer.get("location", "")),
        ("Start Date", offer.get("start_date", "—")),
        ("Reporting Manager", offer.get("reporting_manager", "")),
        ("Annual Compensation (CTC)", offer.get("salary", "—")),
    ]
    summary_rows = [(k, v) for k, v in summary_rows if v]
    summary_table_data = [
        [Paragraph(_e(k), summary_label), Paragraph(_e(v), summary_value)]
        for k, v in summary_rows
    ]
    summary_table = Table(summary_table_data, colWidths=[2.1*inch, 4.65*inch])
    summary_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, DARK),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#D8DEE6")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    content.append(Spacer(1, 4))
    content.append(summary_table)
    content.append(Spacer(1, 6))

    # ---- Compensation & standard clauses — kept compact so a typical letter fits on one page ----
    comp_line = f"Your annual compensation (CTC) will be <b>{_e(offer.get('salary', '—'))}</b>, paid per our standard payroll cycle"
    if offer.get("benefits"):
        comp_line += f", along with benefits including {_e(offer['benefits'])}."
    else:
        comp_line += "."
    if offer.get("probation_period"):
        comp_line += f" This offer includes a probationary period of <b>{_e(offer['probation_period'])}</b> from your start date."
    content.append(Paragraph(comp_line, body))

    work_hours = offer.get("work_hours", "")
    content.append(Paragraph(
        f"Your standard working hours will be {_e(work_hours) if work_hours else 'as communicated by your reporting manager'}. "
        f"This offer and any information shared during the hiring process is confidential and should not be disclosed "
        f"to any third party without prior written consent.", body,
    ))

    closing = "We look forward to having you onboard and seeing your contributions come to life! "
    if offer.get("accept_by"):
        closing += f"Please confirm your acceptance by signing and returning this letter by <b>{_e(offer['accept_by'])}</b>, after which this offer may be withdrawn. "
    closing += "If you have any questions, please reach out using the contact details below."
    content.append(Paragraph(closing, body))
    content.append(Spacer(1, 10))

    # ---- Signature — right-aligned in the corner, the signer's name rendered in their chosen handwriting style ----
    sig_block = [
        Paragraph("Warm Regards,", ParagraphStyle("OLWarmRight", parent=body, alignment=2)),
        Spacer(1, 4),
        Paragraph(_e(offer.get("hr_name", "—")), ParagraphStyle("OLSignScriptRight", parent=sign_script, alignment=2)),
        Spacer(1, 2),
        Paragraph(_e(offer.get("hr_name", "—")), ParagraphStyle("OLSignNameRight", parent=sign_name, alignment=2)),
        Paragraph(_e(offer.get("hr_title", "HR Manager")), ParagraphStyle("OLSignRoleRight", parent=sign_role, alignment=2)),
        Paragraph(_e(offer.get("company_name", "")), ParagraphStyle("OLSignCoRight", parent=sign_role, alignment=2)),
    ]
    sig_table = Table([["", sig_block]], colWidths=[3.5*inch, 3.25*inch])
    sig_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    content.append(sig_table)

    watermark_buf = _make_faded_logo(_logo_stream()) if active_logo else None

    def _footer(canvas_obj, doc_):
        canvas_obj.saveState()
        if watermark_buf:
            try:
                watermark_buf.seek(0)
                wm_size = 3.6 * inch
                canvas_obj.drawImage(
                    ImageReader(watermark_buf),
                    (letter[0] - wm_size) / 2, (letter[1] - wm_size) / 2,
                    width=wm_size, height=wm_size, mask="auto", preserveAspectRatio=True,
                )
            except Exception:
                pass
        canvas_obj.setStrokeColor(colors.HexColor("#D8DEE6"))
        canvas_obj.setLineWidth(0.75)
        canvas_obj.line(0.75*inch, 0.55*inch, letter[0] - 0.75*inch, 0.55*inch)
        canvas_obj.setFillColor(GREY)
        canvas_obj.setFont("Helvetica", 9)
        footer_bits = list(filter(None, [offer.get("company_phone"), offer.get("company_email")]))
        canvas_obj.drawString(0.75*inch, 0.35*inch, "   ·   ".join(footer_bits))
        if active_logo:
            try:
                canvas_obj.drawImage(
                    ImageReader(_logo_stream()), letter[0] - 0.75*inch - 0.32*inch, 0.26*inch,
                    width=0.32*inch, height=0.32*inch, preserveAspectRatio=True,
                    mask="auto", anchor="c",
                )
            except Exception:
                pass
        canvas_obj.restoreState()

    doc.build(content, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
def build_shortlist_report_pdf(candidates: list[dict], job_role: str, weights: dict | None = None,
                                job_details: str = None, key_skills: list | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.55*inch, bottomMargin=0.55*inch,
                             leftMargin=0.6*inch, rightMargin=0.6*inch)
    st_ = _pdf_styles()
    ranked = sorted(
        [c for c in candidates if not c["score"].get("error")],
        key=lambda c: c["score"].get("overall_score", 0), reverse=True,
    )
    weights = weights or {"skills": 40, "experience": 40, "education": 20}

    TEAL = colors.HexColor("#00506B")
    TEAL_LIGHT = colors.HexColor("#E3F5FD")

    rec_style = ParagraphStyle("Rec", parent=st_["body"], fontSize=10.5, leading=15, textColor=colors.HexColor("#0B1C30"))
    footer_style = ParagraphStyle("Footer", parent=st_["sub"], fontSize=8.5, alignment=1, textColor=colors.HexColor("#94A3B8"))

    content = _pdf_header(
        "Ranked Candidate Report",
        f"Job Role: {job_role or '—'} &nbsp;·&nbsp; {len(ranked)} candidate(s) ranked",
    )
    content += _job_details_block(job_role, job_details, key_skills, weights=None)

    # ---- Recruiter Recommendation callout ----
    if ranked:
        top = ranked[0]
        top_s = top["score"]
        top_p = top["profile"]
        matched = ", ".join(top_s.get("matched_skills", [])[:6]) or "no specific skills flagged"
        rec_table = Table([[Paragraph(
            f"<b>Recommended Hire: {top['name']}</b><br/>"
            f"Highest overall score ({top_s.get('overall_score','—')}/100) — matched {matched}, "
            f"{top_p.get('years_experience','—')} experience, education fit "
            f"{top_s.get('breakdown', {}).get('education_fit','—')}/100.",
            rec_style
        )]], colWidths=[6.9*inch])
        rec_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TEAL_LIGHT),
            ("BOX", (0, 0), (-1, -1), 1, TEAL),
            ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        content += [Spacer(1, 4), rec_table, Spacer(1, 12)]

    # ---- Summary stats ----
    scores = [c["score"].get("overall_score", 0) for c in ranked]
    top_score = scores[0] if scores else 0
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    stats_table = Table([[
        Paragraph(f"<b>Top Score</b><br/>{top_score}/100", rec_style),
        Paragraph(f"<b>Total Candidates</b><br/>{len(ranked)}", rec_style),
        Paragraph(f"<b>Average Score</b><br/>{avg_score}/100", rec_style),
        Paragraph(f"<b>Weights</b><br/>Skills {weights.get('skills',40)}% · "
                   f"Exp {weights.get('experience',40)}% · Edu {weights.get('education',20)}%", rec_style),
    ]], colWidths=[1.6*inch, 1.6*inch, 1.6*inch, 2.1*inch])
    stats_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    content += [stats_table, Spacer(1, 14)]

    # ---- Ranked table ----
    content.append(Paragraph(f"Top {min(len(ranked), 10)} Ranked Candidates", ParagraphStyle(
        "H2Teal", parent=st_["h2"], textColor=TEAL)))
    table_data = [["Rank", "Name", "Job Title", "Exp", "Skill %", "Final"]]
    for idx, c in enumerate(ranked[:10], start=1):
        p, s = c["profile"], c["score"]
        b = s.get("breakdown", {})
        table_data.append([
            str(idx), c["name"], job_role or "—",
            str(p.get("years_experience", "—")), f"{b.get('skills_match','—')}",
            f"{s.get('overall_score','—')}",
        ])
    table = Table(table_data, colWidths=[0.5*inch, 1.7*inch, 1.7*inch, 0.7*inch, 0.9*inch, 0.7*inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TEAL_LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    content += [table, Spacer(1, 14)]

    # ---- Why top candidates ranked high ----
    if ranked:
        content.append(Paragraph("Why Top Candidates Ranked High", ParagraphStyle(
            "H2Teal2", parent=st_["h2"], textColor=TEAL)))
        for idx, c in enumerate(ranked[:5], start=1):
            p, s = c["profile"], c["score"]
            skills = ", ".join(s.get("matched_skills", [])[:4]) or "no specific skills flagged"
            content.append(Paragraph(
                f"<b>#{idx} {c['name']}:</b> {skills}; {p.get('years_experience','—')} experience; "
                f"Final {s.get('overall_score','—')}/100", rec_style))
            content.append(Spacer(1, 3))

    content += [
        Spacer(1, 16),
        Paragraph("Generated by ICD Platform — Intelligent Candidate Discovery Platform", footer_style),
    ]
    doc.build(content)
    return buf.getvalue()


def build_interview_report_pdf(interviews: list[dict], job_role: str = None, job_details: str = None,
                                key_skills: list | None = None, weights: dict | None = None) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6*inch, bottomMargin=0.6*inch,
                             leftMargin=0.6*inch, rightMargin=0.6*inch)
    content = _pdf_header("Interview Report", f"{len(interviews)} interview(s)")
    content += _job_details_block(
        job_role, job_details, key_skills, weights,
        note="Context from Resume Screening at export time — individual interviews below may span other roles; see each row's Role column." if job_role else None,
    )
    table_data = [["Candidate", "Role", "Type", "Scheduled", "Status", "Score"]]
    for i in interviews:
        iscore = i.get("interview_score")
        table_data.append([
            i.get("candidate_name", "—"), i.get("job_role") or "—", i.get("interview_type", "—"),
            str(i.get("scheduled_at", "—"))[:16].replace("T", " "),
            i.get("status", "—"),
            f"{iscore}/100" if (i.get("status") == "Completed" and iscore is not None) else "—",
        ])
    table = Table(table_data, colWidths=[1.3*inch, 1.2*inch, 0.9*inch, 1.3*inch, 0.9*inch, 0.7*inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#00506B")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
    ]))
    content.append(table)
    doc.build(content)
    return buf.getvalue()
