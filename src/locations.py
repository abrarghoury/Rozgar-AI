"""
File: src/locations.py
Description: Shared location database for Rozgar AI.

Single source of truth for:
  1. Known Karachi areas + spelling variants (Roman Urdu, Urdu script,
     common Whisper mis-transcriptions) — used by extraction.py to find
     a location inside raw text.
  2. Which district each area belongs to — used by matching.py to score
     proximity (same area > same district > different district).
  3. ALLOWED_DISTRICTS — demo scope, used by generate_seed_data.py so
     seed data and the matching engine never drift out of sync.

ADDING A NEW AREA:
    Add one entry to KARACHI_AREAS (canonical name, district, variants).
    No other code needs to change.

    Keep variants UNIQUE across areas that share a name (e.g. Nazimabad
    vs North Nazimabad) — give the more specific area only variants that
    explicitly include the distinguishing word.
"""

import re

# ---------------------------------------------------------
# canonical_area -> {"district": ..., "variants": [...]}
# ---------------------------------------------------------
KARACHI_AREAS = {
    # ---- Karachi South ----
    "Lyari":        {"district": "Karachi South", "variants": ["lyari", "لیاری"]},
    "Saddar":       {"district": "Karachi South", "variants": ["saddar", "صدر"]},
    "Clifton":      {"district": "Karachi South", "variants": ["clifton", "کلفٹن"]},
    "DHA Phase 5":  {"district": "Karachi South", "variants": ["dha", "ڈی ایچ اے", "دفاع"]},
    "Kharadar":     {"district": "Karachi South", "variants": ["kharadar", "کھارادر"]},
    "Mithadar":     {"district": "Karachi South", "variants": ["mithadar", "میٹھادر"]},
    "Garden":       {"district": "Karachi South", "variants": ["garden", "گارڈن"]},

    # ---- Karachi East ----
    "Gulshan-e-Iqbal":   {"district": "Karachi East", "variants": ["gulshan", "گلشن", "گلچھے", "گلچھو", "گلشن اقبال"]},
    "Gulistan-e-Johar":  {"district": "Karachi East", "variants": ["gulistan-e-johar", "گلستان جوہر", "جوہر"]},
    "Gulzar-e-Hijri":    {"district": "Karachi East", "variants": ["gulzar-e-hijri", "گلزار ہجری"]},
    "Jamshed Town":      {"district": "Karachi East", "variants": ["jamshed town", "جمشید ٹاؤن"]},
    "Bahadurabad":       {"district": "Karachi East", "variants": ["bahadurabad", "بہادر آباد"]},
    "Ferozabad":         {"district": "Karachi East", "variants": ["ferozabad", "فیروز آباد"]},

    # ---- Karachi Central ----
    # NOTE: standalone "نارتھ" (just "North") removed from variants — it is
    # ambiguous (North Karachi also starts with "North") and previously
    # caused any bare "نارتھ" mention to wrongly resolve to North Nazimabad.
    "North Nazimabad": {"district": "Karachi Central", "variants": ["north nazimabad", "نارتھ ناظم آباد"]},
    "Nazimabad":       {"district": "Karachi Central", "variants": ["nazimabad", "ناظم آباد", "ناظمہ باد"]},
    "Liaquatabad":     {"district": "Karachi Central", "variants": ["liaquatabad", "لیاقت آباد"]},
    "Federal B Area":  {"district": "Karachi Central", "variants": ["federal b area", "ایف بی ایریا"]},
    "Gulberg":         {"district": "Karachi Central", "variants": ["gulberg", "گلبرگ"]},
    "New Karachi":     {"district": "Karachi Central", "variants": ["new karachi", "نیو کراچی"]},
    "North Karachi":   {"district": "Karachi Central", "variants": ["north karachi", "نارتھ کراچی"]},

    # ---- Karachi West ----
    "Orangi Town":  {"district": "Karachi West", "variants": ["orangi", "اورنگی"]},
    "Baldia Town":  {"district": "Karachi West", "variants": ["baldia", "بلدیہ"]},
    "Surjani Town": {"district": "Karachi West", "variants": ["surjani", "سرجانی"]},
    "SITE Town":    {"district": "Karachi West", "variants": ["site town", "سائٹ"]},
    "Mominabad":    {"district": "Karachi West", "variants": ["mominabad", "مومن آباد"]},
    "Manghopir":    {"district": "Karachi West", "variants": ["manghopir", "منگھوپیر"]},

    # ---- Korangi ----
    "Korangi":                  {"district": "Korangi", "variants": ["korangi", "کورنگی", "کو رنگی"]},
    "Landhi":                   {"district": "Korangi", "variants": ["landhi", "لنڈی", "لندی"]},
    "Korangi Industrial Area":  {"district": "Korangi", "variants": ["korangi industrial", "کورنگی انڈسٹریل"]},
    "Zaman Town":               {"district": "Korangi", "variants": ["zaman town", "زمان ٹاؤن"]},
    "Shah Faisal Colony":       {"district": "Korangi", "variants": ["shah faisal", "شاہ فیصل"]},

    # ---- Malir ----
    "Malir":          {"district": "Malir", "variants": ["malir", "ملیر"]},
    "Model Colony":   {"district": "Malir", "variants": ["model colony", "ماڈل کالونی"]},
    "Malir Cantt":    {"district": "Malir", "variants": ["malir cantt", "ملیر کینٹ"]},
    "Ibrahim Hyderi": {"district": "Malir", "variants": ["ibrahim hyderi", "ابراہیم حیدری"]},
    "Gadap Town":     {"district": "Malir", "variants": ["gadap", "گڈاپ"]},

    # ---- Kemari ----
    "Kemari":       {"district": "Kemari", "variants": ["kemari", "کیماڑی"]},
    "Native Jetty": {"district": "Kemari", "variants": ["native jetty", "نیٹو جیٹی"]},
    "Mauripur":     {"district": "Kemari", "variants": ["mauripur", "ماوری پور"]},
    "Hawksbay":     {"district": "Kemari", "variants": ["hawksbay", "ہاکس بے"]},
    "Baba Island":  {"district": "Kemari", "variants": ["baba island", "بابا آئی لینڈ"]},
}

# Districts in scope for demo seed data (see generate_seed_data.py)
ALLOWED_DISTRICTS = ["Karachi East", "Karachi Central", "Korangi", "Malir"]


def find_location(text: str) -> str:
    """
    Find a known area inside text. Returns canonical area name or
    "Unknown". Prefers the longest matching variant to avoid partial-
    name confusion (e.g. Nazimabad vs North Nazimabad).

    Uses word-boundary matching (not plain substring) so short variants
    like "dha" don't false-match inside unrelated words (e.g. "adha").
    """
    text_lower = text.lower()

    best_area, best_len = "Unknown", 0
    for area, info in KARACHI_AREAS.items():
        for variant in info["variants"]:
            pattern = r'\b' + re.escape(variant.lower()) + r'\b'
            if re.search(pattern, text_lower) and len(variant) > best_len:
                best_area, best_len = area, len(variant)

    return best_area


def get_district(area: str) -> str:
    """Return the district for a known area, or 'Unknown'."""
    info = KARACHI_AREAS.get(area)
    return info["district"] if info else "Unknown"


def location_proximity_score(area_a: str, area_b: str) -> float:
    """
    same area        -> 1.0
    same district      -> 0.6
    different district  -> 0.3
    either unknown        -> 0.3 (neutral, doesn't punish missing data)
    """
    if area_a == "Unknown" or area_b == "Unknown":
        return 0.3
    if area_a == area_b:
        return 1.0
    if get_district(area_a) == get_district(area_b):
        return 0.6
    return 0.3


def get_areas_by_district(districts: list = None) -> dict:
    """
    Subset of KARACHI_AREAS whose district is in `districts`.
    Defaults to ALLOWED_DISTRICTS. Used by generate_seed_data.py so seed
    data is always pulled live from here, never hardcoded separately.
    """
    if districts is None:
        districts = ALLOWED_DISTRICTS
    return {
        area: info
        for area, info in KARACHI_AREAS.items()
        if info["district"] in districts
    }