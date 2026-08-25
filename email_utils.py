"""
Email delivery for offer letters (and anything else that needs to email a
PDF). Two sending methods are supported, tried in this order:

1. GOOGLE APPS SCRIPT relay (use this if you specifically want Gmail to be
   the one sending) — a tiny script deployed on script.google.com sends via
   MailApp.sendEmail() using YOUR Gmail account, entirely inside Google's
   own servers. Your app just POSTs to the script's webhook URL over HTTPS
   (port 443), so campus/corporate WiFi blocking SMTP ports (587/465)
   doesn't matter — there's no SMTP connection at all. See setup steps in
   the docstring of send_via_google_apps_script() below.

2. SMTP (fallback) — via smtplib, direct to Gmail/Outlook/Yahoo/custom.
   This is the one that gets blocked by networks that block outbound SMTP
   ports — kept as a fallback for networks where it does work.

Whichever secrets are present determines what's used, in the priority order
above. Credentials are intentionally NEVER stored in local_settings.json
(a plain JSON file on disk) — only read from st.secrets/.streamlit/secrets.toml
or environment variables, same pattern ai_engine.py uses for AI provider keys.

Example .streamlit/secrets.toml (Google Apps Script — real Gmail sending):
  GAS_WEBHOOK_URL = "https://script.google.com/macros/s/XXXXX/exec"
  GAS_SECRET = "some-random-string-you-picked"   # shared secret, checked by the script

Example .streamlit/secrets.toml (SMTP):
  SMTP_EMAIL = "hr@yourcompany.com"
  SMTP_APP_PASSWORD = "your-16-char-app-password"
"""

import os
import base64
import smtplib
import requests
import html as _html_mod
import streamlit as st
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email import encoders

SMTP_PRESETS = {
    "Gmail": ("smtp.gmail.com", 587),
    "Outlook / Office 365": ("smtp.office365.com", 587),
    "Yahoo": ("smtp.mail.yahoo.com", 587),
}


def _get_secret(name: str) -> str | None:
    # Same lookup order as ai_engine._get_secret: session override (for
    # quick testing) -> st.secrets -> environment variable.
    try:
        override = st.session_state.get(f"override_{name}")
        if override:
            return override
    except Exception:
        pass
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def get_sender_email() -> str | None:
    return _get_secret("SMTP_EMAIL")


def is_gas_configured() -> bool:
    return bool(_get_secret("GAS_WEBHOOK_URL"))


def is_smtp_configured() -> bool:
    return bool(_get_secret("SMTP_EMAIL") and _get_secret("SMTP_APP_PASSWORD"))


def is_configured() -> bool:
    return is_gas_configured() or is_smtp_configured()


def _extract_logo_theme(logo_bytes: bytes) -> dict:
    """Picks a header background + accent color from the actual logo pixels
    (skipping near-white/near-black/gray/very-dark pixels, which are almost
    always just background or line-art, not the logo's real brand color),
    so the email header reflects the company's own colors instead of a
    fixed generic navy. Always returns a usable theme — falls back to a
    neutral slate if the logo can't be read or has no clear dominant color."""
    fallback = {"header_bg": "#0F172A", "accent": "#378ADD", "badge_text": "#93C5FD"}
    try:
        from PIL import Image as PILImage
        import io as _io
        img = PILImage.open(_io.BytesIO(logo_bytes)).convert("RGBA")
        img.thumbnail((80, 80))
        counts = {}
        for r, g, b, a in img.getdata():
            if a < 128:
                continue
            brightness = (r + g + b) / 3
            if brightness > 232 or brightness < 60:
                continue  # too close to white or too close to black/navy line-art
            if max(r, g, b) - min(r, g, b) < 18:
                continue  # near-gray, not a real brand color
            key = (r // 20 * 20, g // 20 * 20, b // 20 * 20)
            counts[key] = counts.get(key, 0) + 1
        if not counts:
            return fallback
        r, g, b = max(counts.items(), key=lambda kv: kv[1])[0]

        def _clamp(v):
            return max(0, min(255, int(v)))

        def _mix_toward(v, target, frac):
            return _clamp(v + (target - v) * frac)

        # Header background: the brand color darkened toward navy (keeps it
        # readable with white text) but never all the way to black.
        header_bg = "#%02X%02X%02X" % (
            _mix_toward(r, 15, 0.55), _mix_toward(g, 20, 0.55), _mix_toward(b, 30, 0.55),
        )
        # Accent stripe: a brighter, more saturated version of the brand color.
        accent = "#%02X%02X%02X" % (
            _mix_toward(r, 255, 0.25), _mix_toward(g, 255, 0.25), _mix_toward(b, 255, 0.25),
        )
        # Badge text: light enough to read on the dark header pill background.
        badge_text = "#%02X%02X%02X" % (
            _mix_toward(r, 255, 0.55), _mix_toward(g, 255, 0.55), _mix_toward(b, 255, 0.55),
        )
        return {"header_bg": header_bg, "accent": accent, "badge_text": badge_text}
    except Exception:
        return fallback


def _faded_logo_bytes(logo_bytes: bytes, opacity: float = 0.07) -> bytes | None:
    """Bakes a low-opacity version of the logo directly into new PNG pixel
    data (rather than relying on CSS opacity, which many email clients like
    Gmail strip for security reasons). Returns None if the image can't be
    processed — callers should just skip the watermark rather than fail
    the send over it."""
    try:
        from PIL import Image as PILImage
        import io as _io
        img = PILImage.open(_io.BytesIO(logo_bytes)).convert("RGBA")
        alpha = img.getchannel("A").point(lambda p: int(p * opacity))
        img.putalpha(alpha)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _build_branded_email_html(body_text: str, image_src: str | None = None,
                               company_name: str | None = None, badge_text: str = "NOTIFICATION",
                               watermark_src: str | None = None, theme: dict | None = None) -> str:
    """Branded email card: header bar colored from the logo's own dominant
    color (falls back to a neutral slate if there's no logo), the logo
    itself (or company name as text) + a badge, a date line, the message
    body with a pre-faded copy of the logo as a genuine background
    watermark (baked into the image itself — not reliant on CSS opacity,
    which Gmail and others often strip), and a footer. `image_src` /
    `watermark_src` are `cid:...` references (SMTP/GAS inline-embedded
    images). Falls back gracefully to a plain card with just the company
    name (or nothing) if no logo is available — never blocks sending over
    a missing logo."""
    import datetime
    theme = theme or {"header_bg": "#0F172A", "accent": "#378ADD", "badge_text": "#93C5FD"}
    # Preserve blank lines as paragraph breaks (double line-break -> new
    # paragraph with spacing) instead of every single "\n" collapsing into
    # one dense block, so multi-section bodies (offer letters, interview
    # details) read with proper breathing room.
    paragraphs = [p for p in body_text.split("\n\n")]
    body_html = "".join(
        f'<p style="margin:0 0 16px 0;">{_html_mod.escape(p).replace(chr(10), "<br>")}</p>'
        for p in paragraphs if p.strip()
    )
    date_str = datetime.datetime.now().strftime("%d %b %Y")
    company_esc = _html_mod.escape(company_name) if company_name else ""

    if image_src:
        header_left = f'<img src="{image_src}" height="36" alt="{company_esc}" style="display:block; max-height:36px; width:auto;" />'
    elif company_name:
        header_left = f'<span style="color:#ffffff; font-size:19px; font-weight:700; letter-spacing:-0.2px;">{company_esc}</span>'
    else:
        header_left = "&nbsp;"

    # The watermark is a plain (non-positioned) <img> sitting in normal flow
    # ABOVE the text, sized small and faint from the baked-in opacity above
    # — deliberately NOT position:absolute/transform, since Gmail and other
    # clients strip that CSS and were rendering the logo as a huge,
    # undistorted block shoving the message text down instead of sitting
    # quietly behind it. This is the safe middle ground: a genuinely faint
    # logo mark at the top of the message, with zero risk of breaking the
    # layout in any client.
    watermark_html = ""
    if watermark_src:
        watermark_html = (
            f'<div style="text-align:center; margin-bottom:22px;">'
            f'<img src="{watermark_src}" width="120" alt="" style="display:inline-block; width:120px; height:auto;" />'
            f'</div>'
        )

    footer_company = company_esc or "the hiring team"
    return f"""
<div style="max-width:600px; margin:0 auto; font-family:Arial,Helvetica,sans-serif; border:1px solid #E2E8F0; border-radius:14px; overflow:hidden; box-shadow:0 2px 10px rgba(15,23,42,0.06);">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{theme['header_bg']};">
    <tr>
      <td style="padding:22px 26px;">{header_left}</td>
      <td style="padding:22px 26px; text-align:right;">
        <span style="background:rgba(255,255,255,0.14); color:{theme['badge_text']}; font-size:11px; font-weight:700; letter-spacing:0.6px; padding:6px 13px; border-radius:999px; white-space:nowrap;">{_html_mod.escape(badge_text.upper())}</span>
      </td>
    </tr>
  </table>
  <div style="height:3px; background:{theme['accent']};"></div>
  <div style="background:#F8FAFC; padding:10px 26px; text-align:right; font-size:12px; color:#64748B; border-bottom:1px solid #E2E8F0;">{date_str}</div>
  <div style="background:#FFFFFF; padding:30px 26px; font-size:14.5px; color:#1E293B; line-height:1.75;">
    {watermark_html}
    {body_html}
  </div>
  <div style="background:#F8FAFC; padding:14px 26px; border-top:1px solid #E2E8F0; font-size:11.5px; color:#94A3B8; text-align:center;">
    This message was sent by {footer_company}.
  </div>
</div>
""".strip()


def _send_via_google_apps_script(to_email: str, subject: str, body_text: str,
                                  pdf_bytes: bytes, pdf_filename: str,
                                  logo_bytes: bytes | None = None, company_name: str | None = None,
                                  badge_text: str = "NOTIFICATION") -> tuple[bool, str]:
    """
    Sends via a Google Apps Script web app acting as a relay — the script
    runs inside Google's servers and calls MailApp.sendEmail() using YOUR
    Gmail account, so the email genuinely comes from Gmail. Your app only
    makes a plain HTTPS POST to reach it, so SMTP port blocking (common on
    campus/corporate WiFi) is irrelevant here.

    ONE-TIME SETUP (about 5 minutes):
    1. Go to https://script.google.com -> New project.
    2. Delete the default code and paste this in (this version sends a
       branded HTML email — header bar colored from your logo + a badge,
       plus the logo shown faintly as a watermark above the message —
       falling back to a plain-text email automatically if no logo was sent):

        function doPost(e) {
          var data = JSON.parse(e.postData.contents);
          if (data.secret !== "YOUR_SECRET_HERE") {
            return ContentService.createTextOutput(JSON.stringify({error: "bad secret"}));
          }
          var pdfBlob = Utilities.newBlob(
            Utilities.base64Decode(data.pdf_base64), "application/pdf", data.filename
          );
          var mailOptions = {
            to: data.to,
            subject: data.subject,
            body: data.body,
            attachments: [pdfBlob]
          };
          if (data.html_body) {
            mailOptions.htmlBody = data.html_body;
            var inlineImages = {};
            if (data.logo_base64) {
              inlineImages.logo = Utilities.newBlob(
                Utilities.base64Decode(data.logo_base64), "image/png", "logo.png"
              ).setName("logo");
            }
            if (data.watermark_base64) {
              inlineImages.logo_wm = Utilities.newBlob(
                Utilities.base64Decode(data.watermark_base64), "image/png", "logo_wm.png"
              ).setName("logo_wm");
            }
            if (Object.keys(inlineImages).length > 0) {
              mailOptions.inlineImages = inlineImages;
            }
          }
          MailApp.sendEmail(mailOptions);
          return ContentService.createTextOutput(JSON.stringify({ok: true}));
        }

    3. Replace "YOUR_SECRET_HERE" with any random string you make up — this
       stops strangers from finding your URL and using it to spam people.
    4. Click Deploy -> New deployment -> type: Web app.
       - Execute as: Me
       - Who has access: Anyone
    5. Click Deploy, authorize with your Google account when prompted
       (you'll see an "unverified app" warning — that's expected for your
       own personal script; click Advanced -> Go to project (unsafe)).
    6. Copy the Web app URL it gives you (ends in /exec).
    7. Add to .streamlit/secrets.toml:
         GAS_WEBHOOK_URL = "https://script.google.com/macros/s/XXXXX/exec"
         GAS_SECRET = "the-same-random-string-from-step-3"

    Note: if you deployed the script BEFORE this watermark feature was
    added, redeploy it with the updated code above (Deploy -> Manage
    deployments -> Edit -> New version) or the watermark just won't show —
    the plain-text email will still send fine either way.
    """
    webhook_url = _get_secret("GAS_WEBHOOK_URL")
    secret = _get_secret("GAS_SECRET") or ""

    payload = {
        "to": to_email, "subject": subject, "body": body_text,
        "filename": pdf_filename,
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "secret": secret,
    }
    if logo_bytes:
        theme = _extract_logo_theme(logo_bytes)
        faded = _faded_logo_bytes(logo_bytes)
        payload["html_body"] = _build_branded_email_html(
            body_text, "cid:logo", company_name, badge_text,
            watermark_src=("cid:logo_wm" if faded else None), theme=theme,
        )
        payload["logo_base64"] = base64.b64encode(logo_bytes).decode("ascii")
        if faded:
            payload["watermark_base64"] = base64.b64encode(faded).decode("ascii")
    elif company_name:
        payload["html_body"] = _build_branded_email_html(body_text, None, company_name, badge_text)
    try:
        resp = requests.post(webhook_url, json=payload, timeout=25)
        try:
            data = resp.json()
        except Exception:
            data = None
        if resp.status_code == 200 and data and data.get("ok"):
            return True, f"Sent to {to_email} via Gmail."
        error_detail = (data or {}).get("error") if data else resp.text
        return False, f"Google Apps Script returned an error: {error_detail or f'HTTP {resp.status_code}'}"
    except requests.exceptions.Timeout:
        return False, "The Apps Script webhook timed out — check the URL is correct and the script is deployed."
    except requests.exceptions.ConnectionError as e:
        return False, f"Couldn't reach the Apps Script webhook — check your internet connection. ({e})"
    except Exception as e:
        return False, f"Couldn't send via Google Apps Script: {e}"


def _resolve_host_port(provider: str) -> tuple[str, int]:
    if provider in SMTP_PRESETS:
        return SMTP_PRESETS[provider]
    host = _get_secret("SMTP_HOST") or ""
    port = int(_get_secret("SMTP_PORT") or 587)
    return host, port


SSL_PORTS = {
    "Gmail": 465,
    "Outlook / Office 365": 587,  # Outlook doesn't support SSL-on-connect the same way; STARTTLS only
    "Yahoo": 465,
}


def _build_message(sender_email, to_email, subject, body_text, pdf_bytes, pdf_filename, logo_bytes=None,
                    company_name=None, badge_text="NOTIFICATION"):
    msg = MIMEMultipart("mixed")
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject

    if logo_bytes:
        # multipart/related(alternative(plain, branded-html-with-cid-logo), inline-logo-image, inline-watermark-image)
        related = MIMEMultipart("related")
        alternative = MIMEMultipart("alternative")
        theme = _extract_logo_theme(logo_bytes)
        faded = _faded_logo_bytes(logo_bytes)
        alternative.attach(MIMEText(body_text, "plain"))
        alternative.attach(MIMEText(_build_branded_email_html(
            body_text, "cid:logo", company_name, badge_text,
            watermark_src=("cid:logo_wm" if faded else None), theme=theme,
        ), "html"))
        related.attach(alternative)

        logo_img = MIMEImage(logo_bytes, name="logo.png")
        logo_img.add_header("Content-ID", "<logo>")
        logo_img.add_header("Content-Disposition", "inline", filename="logo.png")
        related.attach(logo_img)

        if faded:
            wm_img = MIMEImage(faded, name="logo_wm.png")
            wm_img.add_header("Content-ID", "<logo_wm>")
            wm_img.add_header("Content-Disposition", "inline", filename="logo_wm.png")
            related.attach(wm_img)

        msg.attach(related)
    elif company_name:
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(body_text, "plain"))
        alternative.attach(MIMEText(_build_branded_email_html(body_text, None, company_name, badge_text), "html"))
        msg.attach(alternative)
    else:
        msg.attach(MIMEText(body_text, "plain"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{pdf_filename}"')
    msg.attach(part)
    return msg


def send_plain_email(to_email: str, subject: str, body_text: str, from_email: str | None = None,
                      logo_bytes: bytes | None = None, company_name: str | None = None,
                      badge_text: str = "NOTIFICATION") -> tuple[bool, str]:
    """
    Sends a plain text email with no attachment — used for things like
    verification codes, rejection notices, and interview invites rather than
    documents. Same priority as send_email_with_pdf: Google Apps Script
    (real Gmail) -> SMTP.

    from_email optionally overrides the configured sender:
    - SMTP: only works if it matches (or is a configured alias of) the
      authenticated SMTP_EMAIL account — Gmail/most providers reject a From
      address that doesn't belong to the account that logged in.
    - Google Apps Script: ignored — it always sends as whichever Google
      account authorized the script, there's no way to override that.

    logo_bytes / company_name: same branding as send_email_with_pdf — the
    company's own logo/name in a header bar (never the app's own ICD
    Platform branding). Both optional; omit either or both for a plain-text
    email exactly like before.
    """
    if is_gas_configured():
        webhook_url = _get_secret("GAS_WEBHOOK_URL")
        secret = _get_secret("GAS_SECRET") or ""
        payload = {"to": to_email, "subject": subject, "body": body_text, "filename": "", "pdf_base64": "", "secret": secret}
        if logo_bytes:
            theme = _extract_logo_theme(logo_bytes)
            faded = _faded_logo_bytes(logo_bytes)
            payload["html_body"] = _build_branded_email_html(
                body_text, "cid:logo", company_name, badge_text,
                watermark_src=("cid:logo_wm" if faded else None), theme=theme,
            )
            payload["logo_base64"] = base64.b64encode(logo_bytes).decode("ascii")
            if faded:
                payload["watermark_base64"] = base64.b64encode(faded).decode("ascii")
        elif company_name:
            payload["html_body"] = _build_branded_email_html(body_text, None, company_name, badge_text)
        try:
            resp = requests.post(webhook_url, json=payload, timeout=20)
            # Google Apps Script's ContentService.createTextOutput() returns
            # content-type "text/plain" by default even when the body is
            # valid JSON — gating on that header meant every successful send
            # was misread as a failure ("HTTP 200" error). Just try to parse
            # the body directly instead.
            try:
                data = resp.json()
            except Exception:
                data = {}
            if resp.status_code == 200 and data.get("ok"):
                return True, f"Sent to {to_email}."
            return False, f"Google Apps Script error: {data.get('error') or resp.text[:200] or f'HTTP {resp.status_code}'}"
        except Exception as e:
            return False, f"Couldn't send via Google Apps Script: {e}"

    sender_email = _get_secret("SMTP_EMAIL")
    sender_password = _get_secret("SMTP_APP_PASSWORD")
    if not sender_email or not sender_password:
        return False, ("Email sending isn't configured. Add GAS_WEBHOOK_URL/GAS_SECRET (sends via your real "
                        "Gmail) or SMTP_EMAIL/SMTP_APP_PASSWORD to .streamlit/secrets.toml.")
    try:
        msg = MIMEMultipart("mixed")
        msg["From"] = from_email or sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        if logo_bytes:
            related = MIMEMultipart("related")
            alternative = MIMEMultipart("alternative")
            theme = _extract_logo_theme(logo_bytes)
            faded = _faded_logo_bytes(logo_bytes)
            alternative.attach(MIMEText(body_text, "plain"))
            alternative.attach(MIMEText(_build_branded_email_html(
                body_text, "cid:logo", company_name, badge_text,
                watermark_src=("cid:logo_wm" if faded else None), theme=theme,
            ), "html"))
            related.attach(alternative)
            logo_img = MIMEImage(logo_bytes, name="logo.png")
            logo_img.add_header("Content-ID", "<logo>")
            logo_img.add_header("Content-Disposition", "inline", filename="logo.png")
            related.attach(logo_img)
            if faded:
                wm_img = MIMEImage(faded, name="logo_wm.png")
                wm_img.add_header("Content-ID", "<logo_wm>")
                wm_img.add_header("Content-Disposition", "inline", filename="logo_wm.png")
                related.attach(wm_img)
            msg.attach(related)
        elif company_name:
            alternative = MIMEMultipart("alternative")
            alternative.attach(MIMEText(body_text, "plain"))
            alternative.attach(MIMEText(_build_branded_email_html(body_text, None, company_name, badge_text), "html"))
            msg.attach(alternative)
        else:
            msg.attach(MIMEText(body_text, "plain"))
        host, port = _resolve_host_port("Gmail")
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to_email], msg.as_string())
        return True, f"Sent to {to_email}."
    except Exception as e:
        return False, f"Couldn't send email: {e}"


def send_email_with_pdf(
    to_email: str, subject: str, body_text: str,
    pdf_bytes: bytes, pdf_filename: str, provider: str = "Gmail", from_email: str | None = None,
    logo_bytes: bytes | None = None, company_name: str | None = None, badge_text: str = "JOB OFFER",
) -> tuple[bool, str]:
    """
    Sends an email with a PDF attachment. Returns (success, message) —
    never raises, so the caller can always show a clean result to the user
    instead of a stack trace.

    Priority: Google Apps Script (real Gmail, HTTPS) -> SMTP (blocked by
    some networks' firewalls, kept as a last resort).

    from_email optionally overrides the sender for SMTP — see
    send_plain_email's docstring (SMTP needs to match the authenticated
    mailbox). Ignored for Google Apps Script.

    logo_bytes / company_name: the hiring company's own branding (never the
    app's own ICD Platform logo — same rule as the offer letter PDF). When
    either is provided, the email is sent as a branded HTML card — dark
    header bar with the logo/company name and a badge, date line, then the
    message; when both are omitted, it's a plain-text email exactly like
    before, so this feature is fully optional per-send.
    """
    if is_gas_configured():
        return _send_via_google_apps_script(to_email, subject, body_text, pdf_bytes, pdf_filename,
                                             logo_bytes=logo_bytes, company_name=company_name, badge_text=badge_text)

    import socket

    sender_email = _get_secret("SMTP_EMAIL")
    sender_password = _get_secret("SMTP_APP_PASSWORD")
    if not sender_email or not sender_password:
        return False, ("Email sending isn't configured yet. Add GAS_WEBHOOK_URL/GAS_SECRET (sends via your "
                        "real Gmail) or SMTP_EMAIL and SMTP_APP_PASSWORD to .streamlit/secrets.toml.")

    host, port = _resolve_host_port(provider)
    if not host:
        return False, "No SMTP host configured for a custom provider — add SMTP_HOST to secrets.toml."

    msg = _build_message(from_email or sender_email, to_email, subject, body_text, pdf_bytes, pdf_filename,
                         logo_bytes=logo_bytes, company_name=company_name, badge_text=badge_text)

    def _try_starttls():
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to_email], msg.as_string())

    def _try_ssl():
        ssl_port = SSL_PORTS.get(provider, 465)
        with smtplib.SMTP_SSL(host, ssl_port, timeout=15) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [to_email], msg.as_string())

    try:
        _try_starttls()
        return True, f"Sent to {to_email}."
    except smtplib.SMTPAuthenticationError:
        return False, ("Authentication failed — check SMTP_EMAIL/SMTP_APP_PASSWORD in secrets.toml. "
                        "Make sure you're using an app password, not your regular account password.")
    except (socket.timeout, TimeoutError, ConnectionRefusedError, OSError) as first_err:
        # Connection itself failed (not auth) — retry once over SSL before giving up,
        # since some networks block one port but allow the other.
        if provider in SSL_PORTS:
            try:
                _try_ssl()
                return True, f"Sent to {to_email}."
            except smtplib.SMTPAuthenticationError:
                return False, ("Authentication failed — check SMTP_EMAIL/SMTP_APP_PASSWORD in secrets.toml. "
                                "Make sure you're using an app password, not your regular account password.")
            except Exception:
                pass  # fall through to the timeout message below

        return False, (
            "Couldn't connect to the email server — this is almost always a network/firewall issue, "
            "not a problem with your credentials. A few things to check:\n\n"
            "- Your network, VPN, antivirus, or ISP may be blocking outbound SMTP ports (587/465) — "
            "common on some corporate or campus networks and certain routers.\n"
            "- Try a different network (e.g. mobile hotspot) to confirm this is the cause.\n"
            "- Double-check SMTP_EMAIL and the provider selected match (e.g. don't pick \"Gmail\" for a "
            "non-Gmail address).\n\n"
            f"Technical detail: {first_err}"
        )
    except Exception as e:
        return False, f"Couldn't send the email: {e}"
