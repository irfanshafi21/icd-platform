"""
Reusable UI component library for the ICD Platform.

This centralizes markup/CSS that was previously duplicated across app.py
(skill/gap chip lists, status badges with their own color maps, stat cards,
and button variant styling) into single, consistent functions. Import this
module and use these helpers instead of writing raw HTML inline.
"""

import streamlit as st

# ----------------------------------------------------------------------
# Design tokens (kept in sync with the CSS variables defined in app.py)
# ----------------------------------------------------------------------
COLORS = {
    "primary": "#185FA5",
    "primary_light": "#5FA8FF",
    "success": "#22C55E",
    "success_bg": "#DCFCE7",
    "success_text": "#166534",
    "warning": "#F59E0B",
    "warning_bg": "#FEF3E2",
    "warning_text": "#92400E",
    "danger": "#EF4444",
    "danger_bg": "#FEE2E2",
    "danger_text": "#991B1B",
    "info": "#3B82F6",
    "info_bg": "#DBEAFE",
    "info_text": "#1E40AF",
    "neutral_bg": "#F1F5F9",
    "neutral_text": "#3E484F",
}

# Named status -> variant, so every page that shows the same status string
# (e.g. "Completed", "Rejected") renders it with the same color everywhere.
STATUS_VARIANTS = {
    "Selected": "success", "Completed": "success", "Active": "success", "Strong Fit": "success",
    "Rejected": "danger", "Cancelled": "danger", "Weak Fit": "danger",
    "Scheduled": "info", "Good Fit": "warning",
    "Waiting": "warning", "Pending": "neutral", "Archived": "neutral",
}


def inject_design_system_css():
    """Injects the shared button-variant and chip CSS once per page load.
    Call this near the top of app.py, after page config."""
    st.markdown("""
    <style>
    /* ---- Button variants (applied via styled_button's key-scoped selector) ---- */
    div[data-testid="stButton"] button {
        border-radius: 8px !important;
        transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease !important;
        font-weight: 600 !important;
    }
    div[data-testid="stButton"] button:hover { filter: brightness(0.97); }
    div[data-testid="stButton"] button:active { transform: scale(0.98); }
    div[data-testid="stButton"] button:focus-visible {
        outline: 2px solid #378ADD !important; outline-offset: 2px;
    }

    /* ---- Chips ---- */
    .ds-chip {
        display:inline-block; padding:3px 11px; margin:2px 3px 2px 0;
        border-radius:999px; font-size:0.74rem; font-weight:700; line-height:1.4;
    }
    /* ---- Info / notification panels ---- */
    .ds-panel { border-radius:10px; padding:10px 16px; margin:6px 0; font-size:0.85rem; border:1px solid; }
    </style>
    """, unsafe_allow_html=True)


def styled_button(label, key, variant="secondary", width="content", disabled=False, help=None):
    """A st.button wrapper that applies one of 7 consistent variants:
    primary, secondary, outline, ghost, success, warning, danger.
    'primary'/'secondary' use Streamlit's native button kinds; the rest are
    applied via the key-scoped selector Streamlit exposes for every widget
    (.st-key-{key}), the same technique already used for the sidebar/navbar."""
    native_kind = "primary" if variant == "primary" else "secondary"
    variant_css = {
        "success": "background:#22C55E !important; border-color:#22C55E !important; color:#fff !important;",
        "danger": "background:#EF4444 !important; border-color:#EF4444 !important; color:#fff !important;",
        "warning": "background:#F59E0B !important; border-color:#F59E0B !important; color:#fff !important;",
        "outline": "background:transparent !important; border:1.5px solid #185FA5 !important; color:#185FA5 !important;",
        "ghost": "background:transparent !important; border:none !important; color:#185FA5 !important; box-shadow:none !important;",
    }.get(variant)
    if variant_css:
        st.markdown(f"<style>.st-key-{key} button {{ {variant_css} }}</style>", unsafe_allow_html=True)
    return st.button(
        label, key=key, width=width, disabled=disabled, help=help,
        type=native_kind if variant == "primary" else "secondary",
    )


def chip_list(items, variant="skill", empty_text="—"):
    """Renders a list of strings as chips (skill / gap / neutral variants).
    Replaces the repeated ' '.join(f'<span class=...>{s}</span>' ...) pattern
    used in 8+ places across the Candidates and Home pages."""
    if not items:
        st.caption(empty_text)
        return
    bg, color = {
        "skill": ("#E3F5FD", "#185FA5"),
        "gap": ("#FFF1E6", "#B8541A"),
        "keyword": ("#E3F0FE", "#185FA5"),
        "neutral": (COLORS["neutral_bg"], COLORS["neutral_text"]),
    }.get(variant, (COLORS["neutral_bg"], COLORS["neutral_text"]))
    html = " ".join(
        f'<span class="ds-chip" style="background:{bg}; color:{color};">{item}</span>'
        for item in items
    )
    st.markdown(html, unsafe_allow_html=True)


def status_chip_html(status: str, variant: str = None) -> str:
    """Returns the HTML string for a single status badge, using a shared
    color map (STATUS_VARIANTS) so the same status word always renders
    identically wherever it appears (Home shortlist, Interview tracking,
    Jobs list, etc). Pass `variant` explicitly to override the default map."""
    v = variant or STATUS_VARIANTS.get(status, "neutral")
    palette = {
        "success": (COLORS["success_bg"], COLORS["success_text"]),
        "danger": (COLORS["danger_bg"], COLORS["danger_text"]),
        "warning": (COLORS["warning_bg"], COLORS["warning_text"]),
        "info": (COLORS["info_bg"], COLORS["info_text"]),
        "neutral": (COLORS["neutral_bg"], COLORS["neutral_text"]),
    }.get(v, (COLORS["neutral_bg"], COLORS["neutral_text"]))
    bg, color = palette
    return f'<span class="ds-chip" style="background:{bg}; color:{color};">{status}</span>'


def status_chip(status: str, variant: str = None):
    """Streamlit-rendering version of status_chip_html."""
    st.markdown(status_chip_html(status, variant), unsafe_allow_html=True)


def stat_card_html(icon, label, value, sub=None, color="#0C447C") -> str:
    """Returns the HTML for one Home-page stat card, with a colored circular
    icon badge (color varies per card so the grid isn't monochrome)."""
    sub_html = f'<div class="home-stat-sub">{sub}</div>' if sub else ""
    return f"""
    <div class="home-stat-card">
        <div style="display:flex; align-items:center; justify-content:space-between;">
            <div class="home-stat-label">{label}</div>
            <span class="home-stat-icon" style="background:{color}1A; color:{color}; width:34px; height:34px;
                  border-radius:10px; display:flex; align-items:center; justify-content:center; font-size:1rem;">{icon}</span>
        </div>
        <div class="home-stat-value">{value}</div>
        {sub_html}
    </div>
    """


def info_panel(message: str, variant: str = "info"):
    """A consistent callout/notification panel (info/success/warning/danger)."""
    palette = {
        "info": (COLORS["info_bg"], COLORS["info_text"], COLORS["info"]),
        "success": (COLORS["success_bg"], COLORS["success_text"], COLORS["success"]),
        "warning": (COLORS["warning_bg"], COLORS["warning_text"], COLORS["warning"]),
        "danger": (COLORS["danger_bg"], COLORS["danger_text"], COLORS["danger"]),
    }.get(variant, (COLORS["info_bg"], COLORS["info_text"], COLORS["info"]))
    bg, text, border = palette
    st.markdown(
        f'<div class="ds-panel" style="background:{bg}; color:{text}; border-color:{border};">{message}</div>',
        unsafe_allow_html=True,
    )
