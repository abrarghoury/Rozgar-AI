# app.py
#
# Rozgar AI - Streamlit dashboard, pure Urdu-script UI.
#
# Flow per side (Worker / Employer), same fixed order as before:
#   1) Naam + phone   2) Voice input   3) Editable profile card
#   4) Confirm & save   5) Matches (with Apply/Save/Call/WhatsApp/Share/Suniye)
#
# Plus: sidebar browse/filter (no voice needed), "Job Mil Gaya" status
# toggle on the employer's own listing, "Available/Busy" toggle on the
# worker's own listing, QR flyer, text-to-speech playback.
#
# No emoji anywhere. No raw exception text ever shown to the user.

import sys
import os
import re
import base64
import tempfile
import hashlib
import textwrap
import urllib.parse
from datetime import datetime, timezone
import torch
torch.classes.__path__ = []
import streamlit as st
from audio_recorder_streamlit import audio_recorder

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from speech_to_text import transcribe_audio
from llm_extraction import extract_fields_smart
from storage import (
    add_entry, load_workers, load_employers,
    update_status, update_availability, increment_applicant_count,
)
from matching import find_matches
from locations import KARACHI_AREAS
from tts import text_to_speech_audio
from qr_util import generate_qr_bytes, build_listing_url, build_flyer_contact_card

# ===========================================================
# App-level config
# ===========================================================
# Update this once the app is actually deployed (see PROJECT_REFERENCE
# Section 9) - share links / QR-with-URL only work with a real public
# URL here. Until then this still runs fine locally, the share link
# just won't be openable by anyone except this same machine.
APP_BASE_URL = "http://localhost:8501"

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

# ===========================================================
# PALETTE
# ===========================================================
COLOR_BG = "#F5F1E8"           # warm paper tone - trade/craft, not cold SaaS-grey
COLOR_TEXT = "#211A12"
COLOR_TEXT_MUTED = "#6E6250"
COLOR_CARD_BG = "#FFFFFF"
COLOR_BORDER = "#E7DFCE"

COLOR_PRIMARY = "#1E56A0"      # brand blue - primary buttons, key actions
COLOR_PRIMARY_DARK = "#163F78"
COLOR_WORKER = "#0F6B5C"       # teal - worker-side accent
COLOR_EMPLOYER = "#B5651D"     # ochre - employer-side accent
COLOR_GOLD = "#E8A33D"         # warm accent - hero highlights, stat chips
COLOR_SUCCESS = "#2E7D32"
COLOR_CAUTION = "#C77B2B"
COLOR_ERROR = "#B3261E"
COLOR_URGENT = "#C0392B"

ACCENT = {"worker": COLOR_WORKER, "employer": COLOR_EMPLOYER}

CATEGORY_LABELS = {
    "tradesman": "ہنر مند کاریگر",
    "home_based_woman": "گھر بیٹھے کام کرنے والی خواتین",
    "bulk_staffing": "عام عملہ",
    None: "قسم منتخب نہیں",
}
CATEGORY_KEYS = ["tradesman", "home_based_woman", "bulk_staffing"]
CATEGORY_KEYS_WITH_UNSET = [None] + CATEGORY_KEYS
CATEGORY_KEYS_ANY = ["any"] + CATEGORY_KEYS  # for the browse filter, "any" = no filter

UNKNOWN_LOCATION_LABEL = "نامعلوم"
LOCATION_OPTIONS = [UNKNOWN_LOCATION_LABEL] + sorted(KARACHI_AREAS.keys())
LOCATION_OPTIONS_ANY = ["کوئی بھی علاقہ"] + sorted(KARACHI_AREAS.keys())

# ===========================================================
# Asset loading helpers
# ===========================================================

def _file_as_base64(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


_BACKGROUND_B64 = _file_as_base64(os.path.join(ASSETS_DIR, "Background.png"))
_LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")

# ===========================================================
# PAGE CONFIG + GLOBAL CSS
# ===========================================================
# Logo is used ONLY as the browser tab favicon now - it no longer
# renders as an on-page badge (see hero section below), since it added
# clutter without being needed in the page body itself.
_page_icon = _LOGO_PATH if os.path.exists(_LOGO_PATH) else None
st.set_page_config(page_title="Rozgar AI | روزگار AI", page_icon=_page_icon, layout="wide")

# Hero image: rendered as a real <img> (see hero-image class below), not
# a CSS background-cover box, so the WHOLE picture always shows at full
# width with nothing cropped off any edge. Text used to sit ON TOP of
# this image with a dark scrim before - that both hid the photo and cut
# parts of it. Now the photo stands alone, and all title/slogan/chip
# text lives in panels directly BELOW the photo instead of overlapping it.
_hero_image_src = f"data:image/png;base64,{_BACKGROUND_B64}" if _BACKGROUND_B64 else None

st.markdown(textwrap.dedent(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Nastaliq+Urdu:wght@400;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@600;800&display=swap');

* {{ font-family: 'Noto Nastaliq Urdu', serif; }}

/* Latin digits/labels (stat numbers) get a clean geometric sans - this is
   the ONE deliberate typographic contrast point in the whole page, used
   nowhere else, so it doesn't turn into template noise. */
.num-figure {{ font-family: 'Inter', sans-serif; }}

[data-testid="stAppViewContainer"] {{
    background-color: {COLOR_BG};
    background-image:
        radial-gradient(circle at 100% 0%, rgba(30,86,160,0.10) 0%, transparent 42%),
        radial-gradient(circle at 0% 55%, rgba(181,101,29,0.09) 0%, transparent 38%);
    background-attachment: fixed;
}}
[data-testid="stHeader"] {{ background-color: transparent; }}
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {COLOR_PRIMARY_DARK}, {COLOR_PRIMARY} 55%, {COLOR_PRIMARY_DARK});
    border-right: 1px solid {COLOR_PRIMARY_DARK};
}}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.25); }}
.block-container {{ padding-top: 1rem; }}

/* ---------- Hero ---------- */
.hero-wrap {{
    position: relative;
    border-radius: 22px;
    overflow: hidden;
    margin-bottom: 20px;
    box-shadow: 0 14px 34px rgba(22,32,58,0.22);
    border: 1px solid {COLOR_BORDER};
    background: {COLOR_CARD_BG};
}}
/* Fixed-height frame around the photo. object-fit: contain means the
   FULL image always fits inside this frame (nothing cropped), but the
   frame itself has a capped height - so on a wide screen the image
   can't stretch tall and force extra scrolling on the whole dashboard.
   Any leftover space (if the image is unusually tall/narrow) is just
   letterboxed in the frame's own background color. */
.hero-image-frame {{
    width: 100%;
    height: 260px;
    background: {COLOR_CARD_BG};
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
}}
.hero-image {{
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    object-fit: contain;
    display: block;
}}
.hero-image-fallback {{
    width: 100%;
    height: 260px;
    background: linear-gradient(135deg, {COLOR_PRIMARY_DARK}, {COLOR_PRIMARY});
}}
/* Title panel - plain white card directly under the photo, centered
   title + slogan (Urdu). Kept off the photo entirely so the photo
   always reads clean with zero text on it. */
.hero-text-panel {{
    background: {COLOR_CARD_BG};
    padding: 22px 26px 18px 26px;
    text-align: center;
}}
.hero-text-block {{
    max-width: 680px;
    text-align: center;
    margin: 0 auto;
}}
.hero-title {{
    font-family: 'Noto Nastaliq Urdu', serif;
    font-size: 2.1rem;
    font-weight: 700;
    color: {COLOR_PRIMARY_DARK};
    line-height: 1.6;
}}
.hero-slogan {{
    font-family: 'Noto Nastaliq Urdu', serif;
    font-size: 1rem;
    color: {COLOR_TEXT_MUTED};
    margin-top: 4px;
}}
/* Slim brand-blue strip carrying the "just speak" tagline - a clear
   visual separator between the title block and the category chips. */
.hero-tagline-strip {{
    background: linear-gradient(135deg, {COLOR_PRIMARY_DARK}, {COLOR_PRIMARY});
    padding: 10px 20px;
    text-align: center;
}}
.hero-tagline-strip span {{
    font-family: 'Noto Nastaliq Urdu', serif;
    font-size: 0.95rem;
    color: #FFFFFF;
}}
.hero-chip-row {{
    padding: 14px 26px 20px 26px;
    display: flex; gap: 8px; justify-content: center; flex-wrap: wrap;
    background: {COLOR_CARD_BG};
}}
.hero-chip {{
    font-family: 'Noto Nastaliq Urdu', serif;
    background: {COLOR_BG};
    border: 1px solid {COLOR_BORDER};
    color: {COLOR_PRIMARY_DARK};
    padding: 5px 14px;
    border-radius: 20px;
    font-size: 0.85rem;
}}

/* ---------- Sidebar stat cards (stacked, real data only) ---------- */
.stat-stack {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 4px; }}
.stat-card {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-radius: 12px;
    padding: 10px 14px;
    background: rgba(255,255,255,0.14);
    border: 1px solid rgba(255,255,255,0.22);
    direction: rtl;
}}
.stat-card-label {{
    font-family: 'Noto Nastaliq Urdu', serif;
    font-size: 0.85rem;
    color: rgba(255,255,255,0.85);
}}
.stat-card-value {{
    font-family: 'Inter', sans-serif;
    font-weight: 800;
    font-size: 1.25rem;
    color: #FFFFFF;
}}

/* ---------- Sidebar section headings ---------- */
.sidebar-heading {{
    direction: rtl; text-align: right;
    font-family: 'Noto Nastaliq Urdu', serif;
    font-size: 1.05rem; font-weight: 700;
    color: #FFFFFF;
    border-right: 4px solid {COLOR_GOLD};
    padding-right: 10px;
    margin: 4px 0 8px 0;
}}

/* ---------- Sidebar filter controls (blue theme, tidy) ---------- */
[data-testid="stSidebar"] label {{
    direction: rtl; text-align: right; width: 100%;
    color: rgba(255,255,255,0.85); font-size: 0.92rem;
}}
[data-testid="stSidebar"] [data-baseweb="select"] > div {{
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.3);
    background: rgba(255,255,255,0.95);
}}
[data-testid="stSidebar"] [data-baseweb="select"] > div:focus-within {{
    border-color: {COLOR_GOLD};
    box-shadow: 0 0 0 1px {COLOR_GOLD};
}}
[data-testid="stSidebar"] [role="radiogroup"] {{
    direction: rtl;
    gap: 6px;
}}
[data-testid="stSidebar"] [role="radiogroup"] label {{
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.25);
    border-radius: 10px;
    padding: 6px 12px;
    margin-bottom: 4px;
    color: #FFFFFF;
}}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
    border-color: {COLOR_GOLD};
    background: rgba(232,163,61,0.28);
}}
[data-testid="stSidebar"] [data-baseweb="radio"] div {{ color: #FFFFFF; }}
[data-testid="stSidebar"] .section-caption {{ color: rgba(255,255,255,0.85); }}

/* ---------- Sidebar browse result rows ---------- */
.browse-item {{
    direction: rtl; text-align: right;
    background: rgba(255,255,255,0.95);
    border-right: 3px solid {COLOR_GOLD};
    border-radius: 8px;
    padding: 7px 10px;
    margin-bottom: 6px;
    font-size: 0.87rem;
    color: {COLOR_TEXT};
}}
.browse-more {{
    display: block;
    text-align: center;
    background: {COLOR_GOLD};
    color: {COLOR_PRIMARY_DARK} !important;
    border-radius: 20px;
    padding: 9px 14px;
    font-size: 0.85rem;
    font-weight: 700;
    margin-top: 8px;
    direction: rtl;
    box-shadow: 0 4px 10px rgba(0,0,0,0.20);
}}
.browse-count {{
    direction: rtl; text-align: right;
    color: #FFFFFF; font-weight: 700;
    font-size: 0.9rem; margin-bottom: 8px;
}}
.browse-hint {{
    direction: rtl; text-align: right;
    color: rgba(255,255,255,0.85);
    font-size: 0.87rem;
    background: rgba(255,255,255,0.10);
    border: 1px dashed rgba(255,255,255,0.35);
    border-radius: 10px;
    padding: 10px 12px;
    margin-top: 4px;
}}

/* ---------- Generic text elements ---------- */
.urdu-text {{
    font-family: 'Noto Nastaliq Urdu', serif;
    direction: rtl; text-align: right;
    font-size: 1.15rem; line-height: 2;
    color: {COLOR_TEXT};
}}
.section-caption {{
    direction: rtl; text-align: right;
    color: {COLOR_TEXT_MUTED}; font-size: 0.92rem;
    margin-top: -2px; margin-bottom: 12px;
}}
.step-label {{
    direction: rtl; text-align: right;
    color: {COLOR_PRIMARY}; font-size: 0.9rem; font-weight: 700;
    margin-bottom: 6px;
}}
.location-warning {{
    color: {COLOR_CAUTION}; font-size: 0.9rem;
    margin-top: -6px; margin-bottom: 8px; direction: rtl; text-align: right;
}}
.tag-error {{ color: {COLOR_ERROR}; font-weight: 700; direction: rtl; text-align: right; }}

/* ---------- Cards ---------- */
.profile-card {{
    background: {COLOR_CARD_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 14px;
    padding: 20px 22px;
    margin-bottom: 16px;
    box-shadow: 0 2px 10px rgba(20,40,80,0.06);
    direction: rtl; text-align: right;
}}
.card-title {{ font-size: 1.25rem; font-weight: 700; color: {COLOR_TEXT}; margin: 6px 0 2px 0; }}
.field-row {{ color: {COLOR_TEXT}; font-size: 1rem; margin: 4px 0; }}
.field-label {{ color: {COLOR_TEXT_MUTED}; }}
.card-description {{ color: {COLOR_TEXT}; font-size: 0.98rem; margin: 8px 0; }}
.card-quote {{
    font-size: 0.92rem; color: {COLOR_TEXT_MUTED}; margin-top: 10px;
    border-right: 3px solid {COLOR_BORDER}; padding-right: 10px;
}}
.card-meta {{ color: {COLOR_TEXT_MUTED}; font-size: 0.82rem; margin-top: 10px; }}

/* ---------- Badges ---------- */
.badge {{ display: inline-block; padding: 4px 13px; border-radius: 20px; font-size: 0.8rem; font-weight: 700; margin-left: 6px; }}
.badge-category {{ background: #EEF2FA; color: {COLOR_PRIMARY_DARK}; }}
.badge-good {{ background: {COLOR_SUCCESS}; color: white; }}
.badge-weak {{ background: {COLOR_CAUTION}; color: white; }}
.badge-urgent {{ background: {COLOR_URGENT}; color: white; }}
.badge-filled {{ background: #9AA3AF; color: white; }}

/* ---------- Buttons ---------- */
div.stButton > button {{
    border-radius: 10px; padding: 0.5rem 1.2rem;
    font-family: 'Noto Nastaliq Urdu', serif; font-weight: 700;
    border: 1px solid {COLOR_BORDER};
}}
div.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, {COLOR_PRIMARY}, {COLOR_PRIMARY_DARK});
    border-color: {COLOR_PRIMARY_DARK};
    box-shadow: 0 4px 12px rgba(30,86,160,0.28);
}}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; border-bottom: 2px solid {COLOR_BORDER}; }}
.stTabs [aria-selected="true"] {{
    color: {COLOR_PRIMARY_DARK} !important;
    border-bottom: 3px solid {COLOR_GOLD} !important;
}}

.button-link {{
    display: inline-block; padding: 0.5rem 1.1rem; border-radius: 8px;
    font-family: 'Noto Nastaliq Urdu', serif; font-weight: 700; font-size: 0.95rem;
    text-decoration: none !important; text-align: center; margin: 3px 4px 3px 0;
}}
.button-call {{ background: {COLOR_PRIMARY}; color: white !important; }}
.button-whatsapp {{ background: #25D366; color: white !important; }}

.stTabs [data-baseweb="tab"] {{ font-size: 1.05rem; font-weight: 700; padding: 8px 18px; }}
</style>
"""), unsafe_allow_html=True)

# ===========================================================
# HERO BANNER
# ===========================================================
# Photo band: shows the whole assets/Background.png, uncropped at the
# top, with NOTHING drawn on top of it. Title sits in a plain white
# panel directly under the photo, a thin brand-blue strip carries the
# "just speak" tagline, and the three category chips sit in their own
# row below that - so the photo always stays fully clean and every
# text element gets full contrast regardless of what's in the image.
_hero_image_html = (
    f'<div class="hero-image-frame"><img class="hero-image" src="{_hero_image_src}" alt="" /></div>'
    if _hero_image_src else '<div class="hero-image-fallback"></div>'
)
st.markdown(textwrap.dedent(f"""
<div class="hero-wrap">
  {_hero_image_html}
  <div class="hero-text-panel">
    <div class="hero-text-block">
        <div class="hero-title">روزگار AI</div>
        <div class="hero-slogan">ہر آواز ایک ہنر، ہر ہنر کو روزگار</div>
    </div>
  </div>
  <div class="hero-tagline-strip">
    <span>صرف بولیں - اپنا پروفائل بنائیں یا اپنی ضرورت بتائیں، لکھنے کی ضرورت نہیں</span>
  </div>
  <div class="hero-chip-row">
      <span class="hero-chip">ہنر مند کاریگر</span>
      <span class="hero-chip">گھر بیٹھے خواتین</span>
      <span class="hero-chip">عام عملہ</span>
  </div>
</div>
"""), unsafe_allow_html=True)

# ===========================================================
# HELPERS - text / formatting
# ===========================================================

def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 4:
        return "X" * len(digits)
    return ("X" * (len(digits) - 4)) + digits[-4:]


def valid_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone or "")
    return len(digits) in (10, 11)


def intl_phone(phone: str) -> str:
    """Local 03XXXXXXXXX -> 92XXXXXXXXXX, for wa.me / tel: links."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0"):
        digits = "92" + digits[1:]
    return digits


def relative_time_ur(created_at: str) -> str:
    """ISO timestamp -> Urdu relative time string ('X ghante pehle' etc)."""
    if not created_at:
        return ""
    try:
        then = datetime.fromisoformat(created_at)
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    diff_minutes = int((now - then).total_seconds() // 60)

    if diff_minutes < 2:
        return "ابھی ابھی"
    if diff_minutes < 60:
        return f"{diff_minutes} منٹ پہلے"
    diff_hours = diff_minutes // 60
    if diff_hours < 24:
        return f"{diff_hours} گھنٹے پہلے"
    diff_days = diff_hours // 24
    if diff_days == 1:
        return "کل"
    return f"{diff_days} دن پہلے"


def transcribe_bytes(audio_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_bytes)
        temp_path = tmp.name
    try:
        return transcribe_audio(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def friendly_error(message_ur: str):
    st.markdown(f'<div class="tag-error">{message_ur}</div>', unsafe_allow_html=True)

# ===========================================================
# HELPERS - card rendering
# ===========================================================

def build_card_html(entry: dict, accent: str, contact_label: str, badges_html: str) -> str:
    category_label = CATEGORY_LABELS.get(entry.get("category"), entry.get("category") or "غیر متعین")
    skill = entry.get("skill") or entry.get("role") or "نامعلوم"
    location = entry.get("location", "نامعلوم")
    exp = entry.get("experience_years")
    rate = entry.get("rate_info")
    hours = entry.get("working_hours")
    description = entry.get("description")
    raw_text = entry.get("raw_text", "")
    posted = relative_time_ur(entry.get("created_at"))
    applicant_count = entry.get("applicant_count") or 0

    rows = []
    rows.append(f'<div class="field-row"><span class="field-label">مقام:</span> {location}</div>')
    if exp:
        rows.append(f'<div class="field-row"><span class="field-label">تجربہ:</span> {exp} سال</div>')
    if rate:
        rows.append(f'<div class="field-row"><span class="field-label">اجرت:</span> {rate}</div>')
    if hours:
        rows.append(f'<div class="field-row"><span class="field-label">اوقاتِ کار:</span> {hours}</div>')
    rows.append(f'<div class="field-row"><span class="field-label">رابطہ:</span> {contact_label}</div>')
    rows_html = "\n".join(rows)

    description_html = f'<div class="card-description">{description}</div>' if description else ""

    meta_bits = []
    if posted:
        meta_bits.append(posted)
    meta_bits.append(f"{applicant_count} لوگوں نے دلچسپی ظاہر کی")
    meta_html = " . ".join(meta_bits)

    return textwrap.dedent(f"""
    <div class="profile-card" style="border-right: 5px solid {accent};">
    <span class="badge badge-category">{category_label}</span>{badges_html}
    <div class="card-title">{skill}</div>
    {description_html}
    {rows_html}
    <div class="card-quote">"{raw_text}"</div>
    <div class="card-meta">{meta_html}</div>
    </div>
    """)


def _badges_for(entry: dict, match: dict = None) -> str:
    parts = []
    if entry.get("urgent"):
        parts.append('<span class="badge badge-urgent">فوری ضرورت</span>')
    if entry.get("status") == "filled":
        parts.append('<span class="badge badge-filled">بند ہو چکی ہے</span>')
    if match is not None:
        if match.get("is_weak_match"):
            parts.append('<span class="badge badge-weak">نزدیک ترین دستیاب</span>')
        else:
            parts.append(f'<span class="badge badge-good">اچھی مماثلت - {int(match["score"] * 100)}٪</span>')
    return "".join(parts)


def render_action_row(entry: dict, key_prefix: str, revealed: bool):
    """
    Apply / Save / Call / WhatsApp / Share / Suniye - shown under every
    match card and every browse-list card. Call/WhatsApp only render
    once the phone number has been revealed (same privacy rule as
    before - masked until the person chooses to see it).
    """
    entry_id = entry.get("id", key_prefix)
    entry_type = entry.get("type")
    phone = entry.get("phone", "")

    row1a, row1b, row1c = st.columns(3)
    with row1a:
        applied_key = f"applied_{key_prefix}_{entry_id}"
        if st.session_state.get(applied_key):
            st.markdown('<div class="section-caption">درخواست دے دی گئی ہے</div>', unsafe_allow_html=True)
        else:
            if st.button("درخواست دیں", key=f"apply_{key_prefix}_{entry_id}"):
                increment_applicant_count(entry_type, entry_id)
                st.session_state[applied_key] = True
                st.rerun()
    with row1b:
        saved_ids = st.session_state.setdefault("saved_listing_ids", set())
        if entry_id in saved_ids:
            if st.button("محفوظ شدہ - ہٹائیں", key=f"unsave_{key_prefix}_{entry_id}"):
                saved_ids.discard(entry_id)
                st.rerun()
        else:
            if st.button("محفوظ کریں", key=f"save_{key_prefix}_{entry_id}"):
                saved_ids.add(entry_id)
                st.rerun()
    with row1c:
        reveal_key = f"reveal_{key_prefix}_{entry_id}"
        if not revealed:
            if st.button("رابطہ کریں", key=f"contact_{key_prefix}_{entry_id}"):
                st.session_state[reveal_key] = True
                st.rerun()

    if revealed and phone:
        call_link = f"tel:+{intl_phone(phone)}"
        wa_message = urllib.parse.quote(
            f"Assalam o Alaikum, maine aapki Rozgar AI listing dekhi - {entry.get('skill') or entry.get('role') or ''}, {entry.get('location', '')}."
        )
        wa_link = f"https://wa.me/{intl_phone(phone)}?text={wa_message}"
        st.markdown(
            f'<a href="{call_link}" class="button-link button-call">کال کریں</a>'
            f'<a href="{wa_link}" class="button-link button-whatsapp" target="_blank">واٹس ایپ</a>',
            unsafe_allow_html=True,
        )

    with st.expander("مزید - سنیں / شیئر کریں"):
        listen_col, share_col = st.columns(2)
        with listen_col:
            if st.button("سنیں", key=f"tts_{key_prefix}_{entry_id}"):
                text_for_audio = entry.get("description") or entry.get("raw_text") or ""
                try:
                    audio_bytes = text_to_speech_audio(text_for_audio)
                    st.session_state[f"tts_audio_{key_prefix}_{entry_id}"] = audio_bytes
                except ValueError:
                    friendly_error("آواز ابھی دستیاب نہیں (انٹرنیٹ چیک کریں)۔")
            cached_audio = st.session_state.get(f"tts_audio_{key_prefix}_{entry_id}")
            if cached_audio:
                st.audio(cached_audio, format="audio/mp3")
        with share_col:
            if st.button("شیئر کریں", key=f"share_{key_prefix}_{entry_id}"):
                listing_url = build_listing_url(APP_BASE_URL, entry_id, entry_type)
                try:
                    qr_bytes = generate_qr_bytes(listing_url)
                    st.session_state[f"qr_{key_prefix}_{entry_id}"] = qr_bytes
                except ValueError:
                    friendly_error("شیئر لنک نہیں بن سکا۔")
            cached_qr = st.session_state.get(f"qr_{key_prefix}_{entry_id}")
            if cached_qr:
                st.image(cached_qr, width=140, caption="سکین کر کے دیکھیں")
                wa_share_text = urllib.parse.quote(
                    f"Ye listing dekhein Rozgar AI par: {build_listing_url(APP_BASE_URL, entry_id, entry_type)}"
                )
                st.markdown(
                    f'<a href="https://wa.me/?text={wa_share_text}" class="button-link button-whatsapp" target="_blank">واٹس ایپ سے بھیجیں</a>',
                    unsafe_allow_html=True,
                )


def render_match_card(match: dict, key_prefix: str, accent: str):
    entry = match["entry"]
    entry_id = entry.get("id", key_prefix)
    reveal_key = f"reveal_{key_prefix}_{entry_id}"
    revealed = st.session_state.get(reveal_key, False)
    phone = entry.get("phone", "")
    contact_label = phone if revealed else mask_phone(phone)

    badges = _badges_for(entry, match=match)
    st.markdown(build_card_html(entry, accent, contact_label, badges), unsafe_allow_html=True)
    render_action_row(entry, key_prefix, revealed)


def render_browse_card(entry: dict, key_prefix: str, accent: str):
    entry_id = entry.get("id", key_prefix)
    reveal_key = f"reveal_{key_prefix}_{entry_id}"
    revealed = st.session_state.get(reveal_key, False)
    phone = entry.get("phone", "")
    contact_label = phone if revealed else mask_phone(phone)

    badges = _badges_for(entry, match=None)
    st.markdown(build_card_html(entry, accent, contact_label, badges), unsafe_allow_html=True)
    render_action_row(entry, key_prefix, revealed)

# ===========================================================
# SIDEBAR - stats + browse/filter (no voice needed)
# ===========================================================
with st.sidebar:
    st.markdown('<div class="sidebar-heading">مارکیٹ کے اعداد و شمار</div>', unsafe_allow_html=True)
    all_workers = load_workers()
    all_employers = load_employers()

    # All four numbers below come straight from the same lists already
    # loaded for the browse panel - no invented/placeholder stats.
    open_jobs_count = sum(1 for e in all_employers if e.get("status", "open") != "filled")
    available_workers_count = sum(
        1 for w in all_workers
        if w.get("status", "open") != "filled" and w.get("availability", "available") != "busy"
    )

    def _created_today(entry: dict) -> bool:
        created = entry.get("created_at")
        if not created:
            return False
        try:
            ts = datetime.fromisoformat(created)
        except ValueError:
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).date() == datetime.now(timezone.utc).date()

    joined_today_count = sum(1 for e in (all_workers + all_employers) if _created_today(e))

    st.markdown(textwrap.dedent(f"""
    <div class="stat-stack">
        <div class="stat-card">
            <div class="stat-card-value num-figure">{len(all_workers)}</div>
            <div class="stat-card-label">رجسٹرڈ ورکرز</div>
        </div>
        <div class="stat-card">
            <div class="stat-card-value num-figure">{open_jobs_count}</div>
            <div class="stat-card-label">دستیاب نوکریاں</div>
        </div>
        <div class="stat-card">
            <div class="stat-card-value num-figure">{available_workers_count}</div>
            <div class="stat-card-label">دستیاب ورکرز</div>
        </div>
        <div class="stat-card">
            <div class="stat-card-value num-figure">{joined_today_count}</div>
            <div class="stat-card-label">آج شامل ہوئے</div>
        </div>
    </div>
    """), unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="sidebar-heading">براؤز کریں</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-caption">بغیر آواز کے، فہرست میں تلاش کریں</div>',
        unsafe_allow_html=True,
    )

    browse_target = st.radio("کیا دیکھنا ہے", ["نوکریاں (Jobs)", "ورکرز"], horizontal=False, key="browse_target")
    browse_category = st.selectbox(
        "قسم", CATEGORY_KEYS_ANY, format_func=lambda k: "کوئی بھی قسم" if k == "any" else CATEGORY_LABELS.get(k, k),
        key="browse_category",
    )
    browse_location = st.selectbox("علاقہ", LOCATION_OPTIONS_ANY, key="browse_location")

    # "قسم" (category) or "علاقہ" (location) still sitting on their
    # default "any" value means the person hasn't actually filtered
    # anything yet - in that case we show a prompt instead of dumping
    # every open listing. The "کیا دیکھنا ہے" radio (Jobs vs Workers)
    # doesn't count as a filter here - it's just picking which list to
    # search, so it stays required and doesn't gate the results.
    a_filter_is_chosen = (browse_category != "any") or (browse_location != "کوئی بھی علاقہ")

    if not a_filter_is_chosen:
        st.markdown(
            '<div class="browse-hint">نتائج دیکھنے کے لیے اوپر سے قسم یا علاقہ منتخب کریں</div>',
            unsafe_allow_html=True,
        )
    else:
        if browse_target == "نوکریاں (Jobs)":
            browse_pool = [e for e in all_employers if e.get("status", "open") != "filled"]
        else:
            browse_pool = [
                e for e in all_workers
                if e.get("status", "open") != "filled" and e.get("availability", "available") != "busy"
            ]

        if browse_category != "any":
            browse_pool = [e for e in browse_pool if e.get("category") == browse_category]
        if browse_location != "کوئی بھی علاقہ":
            browse_pool = [e for e in browse_pool if e.get("location") == browse_location]

        st.markdown(f'<div class="browse-count">{len(browse_pool)} نتائج ملے</div>', unsafe_allow_html=True)

        for e in browse_pool[:8]:
            label = f"{e.get('skill') or e.get('role') or ''} - {e.get('location', '')}"
            st.markdown(f'<div class="browse-item">{label}</div>', unsafe_allow_html=True)
        if len(browse_pool) > 8:
            st.markdown(
                f'<div class="browse-more">مزید {len(browse_pool) - 8} نتائج ہیں - تفصیل کے لیے مرکزی صفحے سے تلاش کریں</div>',
                unsafe_allow_html=True,
            )

# ===========================================================
# MAIN FLOW
# ===========================================================

def render_own_listing_controls(entry_type: str, saved_entry: dict, tab_key: str):
    """
    Controls that apply to the person's OWN listing, not to matches.
    Employer: "Job Mil Gaya" status toggle. Worker: availability toggle.
    """
    entry_id = saved_entry.get("id")
    st.markdown('<div class="section-caption">اپنی انٹری کی حالت</div>', unsafe_allow_html=True)

    if entry_type == "employer":
        current_status = saved_entry.get("status", "open")
        col1, col2 = st.columns(2)
        with col1:
            if current_status == "open":
                if st.button("کام مل گیا - بند کریں", key=f"close_{tab_key}"):
                    update_status("employer", entry_id, "filled")
                    saved_entry["status"] = "filled"
                    st.rerun()
            else:
                st.markdown('<div class="section-caption">یہ لسٹنگ بند ہو چکی ہے</div>', unsafe_allow_html=True)
        with col2:
            if current_status == "filled":
                if st.button("دوبارہ کھولیں", key=f"reopen_{tab_key}"):
                    update_status("employer", entry_id, "open")
                    saved_entry["status"] = "open"
                    st.rerun()
    else:
        current_availability = saved_entry.get("availability", "available")
        col1, col2 = st.columns(2)
        with col1:
            if current_availability != "available":
                if st.button("میں دستیاب ہوں", key=f"avail_{tab_key}"):
                    update_availability("worker", entry_id, "available")
                    saved_entry["availability"] = "available"
                    st.rerun()
            else:
                st.markdown('<div class="section-caption">آپ دستیاب ہیں</div>', unsafe_allow_html=True)
        with col2:
            if current_availability != "busy":
                if st.button("میں مصروف ہوں", key=f"busy_{tab_key}"):
                    update_availability("worker", entry_id, "busy")
                    saved_entry["availability"] = "busy"
                    st.rerun()
            else:
                st.markdown('<div class="section-caption">آپ مصروف ہیں</div>', unsafe_allow_html=True)


def run_flow(entry_type: str, tab_key: str):
    accent = ACCENT[entry_type]
    state_key = f"{tab_key}_stage"
    if state_key not in st.session_state:
        st.session_state[state_key] = {"entry_type": entry_type}
    stage = st.session_state[state_key]

    # ---------- STEP 1: Naam + Phone ----------
    if "identity_confirmed" not in stage:
        st.markdown('<div class="step-label">مرحلہ 1 از 4</div>', unsafe_allow_html=True)
        st.markdown('<div class="urdu-text">اپنا نام اور فون نمبر لکھیں</div>', unsafe_allow_html=True)

        name = st.text_input("نام", key=f"name_{tab_key}")
        phone = st.text_input("فون نمبر (مثلاً 03001234567)", key=f"phone_{tab_key}", max_chars=11)

        if st.button("آگے بڑھیں", key=f"continue_{tab_key}", type="primary"):
            if not name.strip():
                friendly_error("نام لکھنا ضروری ہے۔")
            elif not valid_phone(phone):
                friendly_error("فون نمبر درست نہیں ہے۔")
            else:
                stage["name"] = name.strip()
                stage["phone"] = re.sub(r"\D", "", phone)
                stage["identity_confirmed"] = True
                st.rerun()
        return

    # ---------- STEP 2: Voice input ----------
    if "extracted" not in stage:
        st.markdown('<div class="step-label">مرحلہ 2 از 4</div>', unsafe_allow_html=True)
        st.markdown('<div class="urdu-text">اپنی آواز ریکارڈ کریں یا فائل اپلوڈ کریں</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="section-caption">اپنے بارے میں (یا اپنی ضرورت کے بارے میں) بولیں - اجرت اور اوقاتِ کار بھی بتا سکتے ہیں۔</div>',
            unsafe_allow_html=True,
        )

        rec_col, upload_col = st.columns(2)
        with rec_col:
            st.markdown('<div class="urdu-text" style="font-size:1rem;">ریکارڈ کریں</div>', unsafe_allow_html=True)
            recorded_bytes = audio_recorder(
                text="", recording_color=COLOR_ERROR, neutral_color=accent,
                icon_size="2x", pause_threshold=3.0, key=f"recorder_{tab_key}",
            )
        with upload_col:
            st.markdown('<div class="urdu-text" style="font-size:1rem;">یا فائل اپلوڈ کریں</div>', unsafe_allow_html=True)
            uploaded_file = st.file_uploader(
                "آڈیو فائل", type=["mp3", "wav", "m4a", "ogg","mp4"],
                key=f"upload_{tab_key}", label_visibility="collapsed",
            )

        new_audio_bytes = None
        audio_source = None
        if uploaded_file is not None:
            new_audio_bytes = uploaded_file.getvalue()
            audio_source = "upload"
        elif recorded_bytes:
            new_audio_bytes = recorded_bytes
            audio_source = "recording"

        if new_audio_bytes:
            audio_hash = hashlib.md5(new_audio_bytes).hexdigest()
            if stage.get("pending_audio_hash") != audio_hash:
                stage["pending_audio_hash"] = audio_hash
                stage["pending_audio_bytes"] = new_audio_bytes
                stage["pending_audio_source"] = audio_source

        if stage.get("pending_audio_bytes"):
            source_label = "اپلوڈ کی گئی فائل" if stage.get("pending_audio_source") == "upload" else "ریکارڈنگ"
            st.markdown(f'<div class="section-caption">آپ کی {source_label} - پہلے سنیں، پھر تصدیق کریں:</div>', unsafe_allow_html=True)
            st.audio(stage["pending_audio_bytes"])

            confirm_col, rerecord_col = st.columns(2)
            with confirm_col:
                if st.button("یہ ٹھیک ہے - آگے بڑھیں", key=f"use_audio_{tab_key}", type="primary"):
                    with st.spinner("آواز سنی جا رہی ہے، تھوڑا وقت لگ سکتا ہے..."):
                        try:
                            transcript = transcribe_bytes(stage["pending_audio_bytes"])
                        except ValueError:
                            friendly_error("آواز صاف نہیں آئی، دوبارہ ریکارڈ کریں۔")
                            return
                        except Exception:
                            friendly_error("کچھ مسئلہ ہوا، دوبارہ کوشش کریں۔")
                            return
                    stage["transcript"] = transcript
                    with st.spinner("پروفائل بنایا جا رہا ہے..."):
                        try:
                            result = extract_fields_smart(transcript)
                            result["type"] = entry_type
                            stage["extracted"] = result
                        except Exception:
                            friendly_error("تفصیل نہیں نکل سکی، دوبارہ کوشش کریں۔")
                            return
                    st.rerun()
            with rerecord_col:
                if st.button("دوبارہ ریکارڈ کریں", key=f"clear_audio_{tab_key}"):
                    stage.pop("pending_audio_bytes", None)
                    stage.pop("pending_audio_hash", None)
                    stage.pop("pending_audio_source", None)
                    st.rerun()
        return

    # ---------- STEP 3: Editable profile card ----------
    if "saved_entry" not in stage:
        st.markdown('<div class="step-label">مرحلہ 3 از 4</div>', unsafe_allow_html=True)
        extracted = stage["extracted"]

        st.markdown('<div class="urdu-text">اپنی تفصیل چیک کریں</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-caption">نیچے دی گئی ہر تفصیل چیک کریں - جو غلط لگے اسے درست کریں۔</div>', unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            current_category = extracted.get("category")
            cat_index = (
                CATEGORY_KEYS_WITH_UNSET.index(current_category)
                if current_category in CATEGORY_KEYS_WITH_UNSET else 0
            )
            chosen_category = st.selectbox(
                "قسم", CATEGORY_KEYS_WITH_UNSET, index=cat_index,
                format_func=lambda k: CATEGORY_LABELS.get(k, k), key=f"category_{tab_key}",
            )
            extracted["category"] = chosen_category
            if chosen_category is None:
                st.markdown('<div class="location-warning">قسم منتخب نہیں کی گئی - براہ کرم منتخب کریں۔</div>', unsafe_allow_html=True)

            chosen_skill = st.text_input("ہنر / کام", value=extracted.get("skill") or "", key=f"skill_{tab_key}")
            chosen_skill = chosen_skill.strip() or None
            extracted["skill"] = chosen_skill
            if not chosen_skill:
                st.markdown('<div class="location-warning">ہنر خالی ہے - مماثلت کے لیے یہ لازمی ہے۔</div>', unsafe_allow_html=True)

            chosen_rate = st.text_input("اجرت (مثلاً 500 روپے فی کام، یا 25000 روپے ماہانہ)", value=extracted.get("rate_info") or "", key=f"rate_{tab_key}")
            extracted["rate_info"] = chosen_rate.strip() or None

        with col2:
            current_location = extracted.get("location") or UNKNOWN_LOCATION_LABEL
            if current_location not in LOCATION_OPTIONS:
                current_location = UNKNOWN_LOCATION_LABEL
            loc_index = LOCATION_OPTIONS.index(current_location)
            chosen_location = st.selectbox("مقام / علاقہ", LOCATION_OPTIONS, index=loc_index, key=f"location_{tab_key}")
            extracted["location"] = chosen_location
            if chosen_location == UNKNOWN_LOCATION_LABEL:
                st.markdown('<div class="location-warning">علاقہ نہیں ملا - براہ کرم منتخب کریں۔</div>', unsafe_allow_html=True)

            chosen_experience = st.number_input(
                "تجربہ (سال)", min_value=0, max_value=60,
                value=int(extracted.get("experience_years") or 0), key=f"experience_{tab_key}",
            )
            extracted["experience_years"] = chosen_experience if chosen_experience > 0 else None

            chosen_hours = st.text_input("اوقاتِ کار (مثلاً 8 گھنٹے، نائٹ شفٹ)", value=extracted.get("working_hours") or "", key=f"hours_{tab_key}")
            extracted["working_hours"] = chosen_hours.strip() or None

        chosen_description = st.text_area(
            "مختصر تفصیل", value=extracted.get("description") or "", key=f"desc_{tab_key}", height=70,
        )
        extracted["description"] = chosen_description.strip() or None

        if entry_type == "employer":
            extracted["urgent"] = st.checkbox("فوری ضرورت ہے", value=bool(extracted.get("urgent")), key=f"urgent_{tab_key}")

        secondary = extracted.get("secondary_skills") or []
        if secondary:
            st.markdown(f'<div class="section-caption">یہ بھی ذکر ہوا: {"، ".join(secondary)}</div>', unsafe_allow_html=True)

        with st.expander("ٹرانسکرپٹ دیکھیں / ریکارڈنگ کا مکمل متن"):
            st.text_area("ٹرانسکرپٹ", value=stage.get("transcript", ""), key=f"transcript_view_{tab_key}", height=80, disabled=True, label_visibility="collapsed")

        confirm_col, redo_col = st.columns(2)
        with confirm_col:
            if st.button("تصدیق کریں اور محفوظ کریں", key=f"save_{tab_key}", type="primary"):
                entry_to_save = dict(extracted)
                entry_to_save["name"] = stage["name"]
                entry_to_save["phone"] = stage["phone"]
                saved = add_entry(entry_to_save)
                stage["saved_entry"] = saved
                st.rerun()
        with redo_col:
            if st.button("دوبارہ ریکارڈ کریں", key=f"redo_{tab_key}"):
                for k in ("extracted", "transcript", "pending_audio_bytes", "pending_audio_hash", "pending_audio_source"):
                    stage.pop(k, None)
                st.rerun()
        return

    # ---------- STEP 4: Matches ----------
    st.markdown('<div class="step-label">مرحلہ 4 از 4</div>', unsafe_allow_html=True)
    st.success("پروفائل محفوظ ہو گئی ہے۔")

    with st.container():
        render_own_listing_controls(entry_type, stage["saved_entry"], tab_key)

    st.markdown('<div class="urdu-text">دستیاب مواقع</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-caption">ہنر اور مقام کے حساب سے ترتیب دیا گیا۔</div>', unsafe_allow_html=True)

    try:
        matches = find_matches(stage["saved_entry"], top_n=5)
    except Exception:
        friendly_error("مماثلت ابھی کام نہیں کر رہی، تھوڑی دیر میں دوبارہ کوشش کریں۔")
        matches = []

    # NOTE: busy workers are already excluded upstream, inside
    # matching.py's _load_open_candidates() (same place status=="filled"
    # is filtered) - no need to filter again here.

    if not matches:
        st.info("ابھی کوئی مماثلت نہیں ملی، ہم آپ کو مطلع کریں گے۔")
    else:
        for m in matches:
            render_match_card(m, key_prefix=tab_key, accent=accent)

    saved_ids = st.session_state.get("saved_listing_ids", set())
    if saved_ids:
        with st.expander(f"محفوظ شدہ فہرست ({len(saved_ids)})"):
            all_pool = load_workers() + load_employers()
            for e in all_pool:
                if e.get("id") in saved_ids:
                    st.markdown(f'<div class="section-caption">{e.get("skill") or e.get("role")} - {e.get("location")}</div>', unsafe_allow_html=True)

    if st.button("نئی انٹری شامل کریں", key=f"reset_{tab_key}"):
        st.session_state[state_key] = {"entry_type": entry_type}
        st.rerun()


# ===========================================================
# TABS
# ===========================================================
tab_worker, tab_employer = st.tabs(["میں کام ڈھونڈ رہا ہوں", "مجھے ورکر چاہیے"])

with tab_worker:
    run_flow(entry_type="worker", tab_key="worker")

with tab_employer:
    run_flow(entry_type="employer", tab_key="employer")
