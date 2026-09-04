# src/qr_util.py
#
# QR code generation for two separate features:
#   1. Printable flyer (PROJECT_REFERENCE Section 6, item 23) - encodes
#      a MECARD contact card, works fully offline, no deployment needed.
#      Scanning it on any phone offers to save the person as a contact
#      directly - useful even before the app is hosted anywhere public.
#   2. WhatsApp share-link (item 13) - encodes a deep link into the
#      deployed app. Only meaningful once the app has a real public URL
#      (PROJECT_REFERENCE Section 9) - on localhost the QR still
#      generates, but the link it encodes is unusable to anyone else.
#
# generate_qr_bytes() itself is generic (any string -> PNG) - the two
# functions below just build the right string for each use case.
#
# Usage: python src/qr_util.py "https://example.com/?listing=E045"

import sys
import io
import qrcode


def generate_qr_bytes(data: str) -> bytes:
    """
    Turns any string (a URL, MECARD contact card, or plain text) into
    a PNG image, returned as raw bytes so app.py can hand it straight
    to st.image() without touching disk.

    Raises:
        ValueError if data is empty - nothing meaningful to encode.
        Anything else from the qrcode library is left to propagate as-is
        (unlike tts.py/speech_to_text.py, this has no external dependency
        that can flake out mid-run, so there's no broad "who knows what
        went wrong" case to protect against here).
    """
    if not data or not data.strip():
        raise ValueError("QR code ke liye koi data nahi diya gaya.")

    qr = qrcode.QRCode(
        version=None,          # auto-sizes to fit the data
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


def build_listing_url(base_url: str, entry_id: str, entry_type: str) -> str:
    """
    Builds the shareable deep-link for a single listing, using query
    parameters app.py reads on load to jump straight to that listing.
    base_url needs to be the app's actual deployed URL (e.g.
    "https://rozgar-ai.streamlit.app") - this only works once the app
    is hosted somewhere public. On localhost the link is still
    generated correctly but is meaningless to anyone except the person
    running that same localhost instance.
    """
    base_url = base_url.rstrip("/")
    return f"{base_url}/?listing={entry_id}&type={entry_type}"


def _escape_mecard(value: str) -> str:
    # MECARD uses ',' and ';' as delimiters - escape them if they show
    # up inside a name/phone/note so the card doesn't get corrupted.
    return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")


def build_flyer_contact_card(entry: dict) -> str:
    """
    Builds a MECARD-format contact card string for the printable flyer
    (item 23) - works fully offline, no deployed URL needed. Most phone
    QR scanners recognize MECARD automatically and offer to save it as
    a new contact directly.

    Input:
        entry: a structured entry dict (worker or employer) - expects
               at least "name" and "phone"; skill/role, location,
               experience_years, rate_info, working_hours are folded
               into the NOTE field if present.

    Raises:
        ValueError if entry has no phone number (a contact card with
        no way to reach the person isn't useful).
    """
    phone = entry.get("phone")
    if not phone:
        raise ValueError("Entry mein phone number nahi hai - contact card nahi ban sakta.")

    name = entry.get("name") or "Rozgar AI Contact"

    note_parts = []
    skill = entry.get("skill") or entry.get("role")
    if skill:
        note_parts.append(skill)
    if entry.get("location") and entry["location"] != "Unknown":
        note_parts.append(entry["location"])
    if entry.get("experience_years"):
        note_parts.append(f"{entry['experience_years']} saal ka tajurba")
    if entry.get("rate_info"):
        note_parts.append(entry["rate_info"])
    if entry.get("working_hours"):
        note_parts.append(entry["working_hours"])
    note = " - ".join(note_parts) if note_parts else "Rozgar AI listing"

    return f"MECARD:N:{_escape_mecard(name)};TEL:{_escape_mecard(phone)};NOTE:{_escape_mecard(note)};;"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python src/qr_util.py "some text or URL"')
        sys.exit(1)

    input_data = sys.argv[1]
    print(f"[qr_util] Encoding: {input_data}")
    png_bytes = generate_qr_bytes(input_data)
    out_path = "qr_test_output.png"
    with open(out_path, "wb") as f:
        f.write(png_bytes)
    print(f"[qr_util] Saved {len(png_bytes)} bytes to {out_path}")

    # also demo the flyer contact-card path (offline, no args needed)
    demo_entry = {
        "name": "Asif",
        "phone": "0312-9647849",
        "skill": "Electrician",
        "location": "Korangi",
        "experience_years": 5,
        "rate_info": "500 rupees per kaam",
    }
    card_data = build_flyer_contact_card(demo_entry)
    flyer_bytes = generate_qr_bytes(card_data)
    flyer_path = "qr_flyer_test_output.png"
    with open(flyer_path, "wb") as f:
        f.write(flyer_bytes)
    print(f"[qr_util] Flyer contact-card QR saved to {flyer_path} "
          f"(scan to save '{demo_entry['name']}' as a contact)")