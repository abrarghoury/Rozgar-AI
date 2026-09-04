# File: src/extraction.py
# Rule-based extractor (no API, no internet). Pulls structured fields
# out of raw transcript text using keyword matching + a fuzzy fallback
# for Whisper noise. This is the offline safety net for llm_extraction.py
# - same output shape, so the rest of the app doesn't care which one
# produced the data.
#
# Usage: python src/extraction.py "main gulshan mein rehta hoon AC fitting ka kaam panch saal se karta hoon"

import re
import sys
import json
import difflib

# Works both when this file is run directly (python src/extraction.py)
# and when imported as a package member (from src.extraction import ...),
# e.g. from app.py or matching.py.
try:
    from src.locations import find_location
except ImportError:
    from locations import find_location

# Skill keyword table. category is one of: tradesman | home_based_woman | bulk_staffing
# Keep variants lowercase-safe (matching lowercases text before comparing).
SKILLS = {
    # tradesmen
    "Electrician":    (["electrician", "الیکٹریشن", "الیکٹیشن", "wiring", "وائرنگ", "وائیرنگ",
                          "electrical fitting", "ایلیکٹرکل فیٹنگ", "الیکٹرکل فیٹنگ"], "tradesman"),
    "AC Technician":  (["ac fitting", "اے سی فیٹنگ", "ایسی فیٹنگ", "اسی فیٹنگ"], "tradesman"),
    "Plumber":        (["plumber", "پلمبر", "پلمبنگ", "pani ki line"], "tradesman"),
    "Auto Mechanic":  (["gari ki mistri", "mechanic", "میکینک", "گاڑی کی مستری"], "tradesman"),
    "Carpenter":      (["carpenter", "کارپینٹر", "لکڑی کا کام", "بڑھئی"], "tradesman"),
    "Painter":        (["painter", "پینٹر", "پینٹنگ"], "tradesman"),
    "Welder":         (["welder", "ویلڈر", "ویلڈنگ"], "tradesman"),

    # home-based women
    "Tailoring / Darzan": (["kapre seeti", "کپڑے سیتی", "silai", "سلائی", "darzan", "درزن"], "home_based_woman"),
    "Home Tutor":     (["parhati", "پڑھاتی", "پڑھا", "tutor", "ٹیوٹر", "ٹویٹر", "tuition", "ٹیوشن"], "home_based_woman"),
    "Embroidery / Kasheeda": (["kashidakari", "کشیدہ کاری", "embroidery"], "home_based_woman"),
    "Cook / Chef":    (["khana banane", "کھانا بنانے", "cook", "کک", "باورچی", "chef", "شیف", "tiffin"], "home_based_woman"),

    # bulk / general staffing
    "Security Guard": (["guard", "گارڈ", "گارٹ", "گاٹ", "security"], "bulk_staffing"),
    "Construction Labour": (["mazdoor", "مزدور", "labour", "construction"], "bulk_staffing"),
    "Domestic Helper": (["ghar ka kaam", "گھر کا کام", "helper", "ہیلپر"], "bulk_staffing"),
    "Driver":         (["driver", "ڈرائیور", "driving"], "bulk_staffing"),
    "Loader / Helper": (["loading", "لوڈنگ", "godam", "گودام"], "bulk_staffing"),
    "Gardener":       (["mali", "مالی", "gardener", "gardening", "باغبانی"], "bulk_staffing"),
    "Cleaner":        (["safai", "صفائی", "cleaner", "cleaning"], "bulk_staffing"),
    "Delivery Boy":   (["delivery", "ڈیلیوری"], "bulk_staffing"),
}

# words that flag "someone asking for a worker" vs "someone describing themselves"
EMPLOYER_SIGNALS = [
    "chahiye", "چاہیے", "چاہی", "zarurat", "ضرورت", "chahye",
    "humein", "ہمیں", "mujhe.*chahiye",
]
WORKER_SIGNALS = [
    "karta hoon", "کرتا ہوں", "karti hoon", "کرتی ہوں",
    "rehta hoon", "رہتا ہوں", "rehti hoon", "رہتی ہوں", "ریتی ہوں",
    "tajurba", "تجربہ", "seeti hoon", "سیتی ہوں",
]

# number words -> digit, used for experience_years parsing
NUMBER_WORDS = {
    "aik": 1, "ek": 1, "ایک": 1,
    "do": 2, "دو": 2,
    "teen": 3, "تین": 3,
    "char": 4, "chaar": 4, "چار": 4,
    "panch": 5, "paanch": 5, "پانچ": 5,
    "chay": 6, "chhay": 6, "چھ": 6,
    "saat": 7, "سات": 7, "سا": 7,   # "سا" is Whisper's garbled "سات" - seen in real transcripts
    "aath": 8, "آٹھ": 8,
    "nau": 9, "نو": 9,
    "das": 10, "دس": 10,
}

# keywords that mean a pay/rate figure is probably nearby
RATE_KEYWORDS = [
    "rupees", "روپے", "rupay", "rupaye", "rupya",
    "hazar", "ہزار", "salary", "تنخواہ", "rate", "ریٹ", "price", "قیمت",
]

# keywords that mean working hours / shift info is probably nearby
HOUR_KEYWORDS = [
    "ghante", "گھنٹے", "ghanta", "گھنٹہ", "shift", "شفٹ",
    "night shift", "نائٹ شفٹ", "din", "دن میں",
]


def _exact_match(text, variants):
    text_lower = text.lower()
    return any(variant.lower() in text_lower for variant in variants)


def _fuzzy_match(text, variants, cutoff=0.82):
    # only called when nothing matched exactly. cutoff is high on purpose -
    # short Urdu words look similar to each other and low cutoff gives false hits
    words = text.lower().split()
    for variant in variants:
        if len(variant) < 4:
            continue  # too short to fuzzy match reliably
        matches = difflib.get_close_matches(variant.lower(), words, n=1, cutoff=cutoff)
        if matches:
            return True
    return False


def extract_location(text):
    # actual area/district table lives in locations.py, shared with matching.py
    return find_location(text)


def extract_skill_and_category(text):
    # thin wrapper kept for backwards compatibility - callers that don't
    # care about secondary skills can just use this
    skill_name, category, _secondary = extract_skill_and_category_detailed(text)
    return skill_name, category


def extract_skill_and_category_detailed(text):
    # Picks the skill whose keyword appears EARLIEST in the sentence, not
    # the longest keyword match. Longest-match was wrong: "AC fitting aur
    # wiring ka kaam karta hoon" was picking "Electrician" because "wiring"
    # is a longer string than "اسی فیٹنگ", even though AC Technician is
    # clearly the primary trade being described. First-mentioned == primary,
    # in practice, across every real transcript we tested.
    text_lower = text.lower()
    candidates = []  # (position, -length, skill_name, category)

    for skill_name, (variants, category) in SKILLS.items():
        best_pos = None
        best_len = 0
        for variant in variants:
            pos = text_lower.find(variant.lower())
            if pos != -1 and (best_pos is None or pos < best_pos):
                best_pos = pos
                best_len = len(variant)
        if best_pos is not None:
            candidates.append((best_pos, -best_len, skill_name, category))

    if candidates:
        candidates.sort(key=lambda c: (c[0], c[1]))  # earliest position wins, longest match breaks ties
        _, _, primary_skill, primary_category = candidates[0]
        secondary_skills = [c[2] for c in candidates[1:]]
        return primary_skill, primary_category, secondary_skills

    # nothing matched exactly - last resort, fuzzy match single skill only
    for skill_name, (variants, category) in SKILLS.items():
        if _fuzzy_match(text, variants):
            return skill_name, category, []

    return None, None, []


def extract_type(text):
    text_lower = text.lower()
    for signal in EMPLOYER_SIGNALS:
        if re.search(signal, text_lower):
            return "employer"
    for signal in WORKER_SIGNALS:
        if signal.lower() in text_lower:
            return "worker"
    return "worker"  # unclear -> assume worker, safer default for this app


def extract_experience_years(text):
    # only counts a number if "saal"/"سال" follows it directly - avoids
    # false positives like "ایک الیکٹیشن" (one electrician) reading as "1 year"
    digit_match = re.search(r"(\d+)\s*(saal|سال)", text, re.IGNORECASE)
    if digit_match:
        return int(digit_match.group(1))

    words = text.lower().split()
    for i, word in enumerate(words):
        clean_word = word.strip(",،.")
        if clean_word in NUMBER_WORDS:
            lookahead = " ".join(words[i + 1:i + 3])  # check next couple words for "saal"
            if "saal" in lookahead or "سال" in lookahead:
                return NUMBER_WORDS[clean_word]

    return None


def _first_keyword_pos(clause, keywords):
    # returns the earliest position (index) at which ANY keyword from the
    # list occurs in the clause, or None if no keyword is present.
    clause_lower = clause.lower()
    best_pos = None
    for kw in keywords:
        pos = clause_lower.find(kw.lower())
        if pos != -1 and (best_pos is None or pos < best_pos):
            best_pos = pos
    return best_pos


def _split_mixed_clause(clause):
    # Real Whisper transcripts are often punctuation-free, so a rate phrase
    # and an hours phrase can end up stuck together in ONE clause with no
    # comma between them, e.g. "25000 rupees mahana 8 ghante ki shift".
    # Only step in when a clause has BOTH a rate keyword AND an hour
    # keyword - if it has only one type (e.g. the tailor two-price example,
    # "sada suit 500 rupees"), leave it untouched so descriptive context
    # words aren't stripped away here (see _trim_leading_context for that).
    #
    # Split point: right before any digit-run that isn't the clause's very
    # first token - spoken price/hours are almost always said as fresh
    # "<amount> <unit word>" phrases back-to-back, so a new number marks
    # the natural start of the next phrase.
    has_rate = _first_keyword_pos(clause, RATE_KEYWORDS) is not None
    has_hour = _first_keyword_pos(clause, HOUR_KEYWORDS) is not None
    if not (has_rate and has_hour):
        return [clause]

    tokens = clause.split()
    split_at = [0] + [i for i, tok in enumerate(tokens) if i > 0 and re.match(r"^\d+$", tok)]
    split_at.append(len(tokens))
    split_at = sorted(set(split_at))

    segments = [" ".join(tokens[a:b]).strip() for a, b in zip(split_at, split_at[1:])]
    segments = [s for s in segments if s]
    return segments if len(segments) > 1 else [clause]


def _split_clauses(text):
    # first pass: split on commas/periods/urdu comma so each clause can be
    # checked independently - avoids the character-window approach bleeding
    # rate info into hours info (or vice versa) when both are mentioned
    # close together in one sentence.
    # second pass: _split_mixed_clause() further splits any clause that
    # still contains BOTH a rate and an hour keyword (see its docstring).
    raw_clauses = [c.strip() for c in re.split(r"[,،.]", text) if c.strip()]
    clauses = []
    for c in raw_clauses:
        clauses.extend(_split_mixed_clause(c))
    return clauses


def _trim_leading_context(clause, max_context_words=2):
    # A clause can still carry a long, unrelated preamble glued to a price/
    # hours phrase when the speaker never paused before switching topic
    # (no comma to split on at all), e.g. "main silai ka kaam karti hoon
    # sada suit 500 rupees" - the worker's opening sentence and the actual
    # price statement are ONE clause with no separator. Trim to the last
    # couple words before the first digit run so unrelated preamble
    # ("main silai ka kaam karti hoon") is dropped, while short, meaningful
    # context sitting right next to the number ("sada suit") is kept -
    # matches the doc's tailor two-price example exactly.
    tokens = clause.split()
    digit_idx = next((i for i, t in enumerate(tokens) if re.match(r"^\d+$", t)), None)
    if digit_idx is None or digit_idx <= max_context_words:
        return clause  # short/no-number clause - nothing unrelated to trim
    start = digit_idx - max_context_words
    return " ".join(tokens[start:])


def extract_rate_info(text):
    # Deliberately NOT parsed into a number. Pay varies too much by
    # category to force into one field - a tailor might quote two
    # different prices in one breath ("sada suit 500, design wala 1200"),
    # a guard gives one monthly figure. So we return the clause(s) that
    # mention pay, as-is (trimmed of unrelated leading context). Display
    # only - never fed into the matching score.
    clauses = _split_clauses(text)
    matched = []
    for c in clauses:
        rate_pos = _first_keyword_pos(c, RATE_KEYWORDS)
        if rate_pos is None:
            continue
        hour_pos = _first_keyword_pos(c, HOUR_KEYWORDS)
        if hour_pos is not None and hour_pos < rate_pos:
            continue  # hours keyword comes first in this clause, let extract_working_hours take it
        matched.append(_trim_leading_context(c))
    return ", ".join(matched) if matched else None


def extract_working_hours(text):
    # mirror of extract_rate_info()'s clause ownership + trimming logic
    clauses = _split_clauses(text)
    matched = []
    for c in clauses:
        hour_pos = _first_keyword_pos(c, HOUR_KEYWORDS)
        if hour_pos is None:
            continue
        rate_pos = _first_keyword_pos(c, RATE_KEYWORDS)
        if rate_pos is not None and rate_pos < hour_pos:
            continue  # rate keyword comes first in this clause, extract_rate_info already took it
        matched.append(_trim_leading_context(c))
    return ", ".join(matched) if matched else None


def build_fallback_description(fields):
    # Rule-based extraction has no language model to write a natural
    # sentence, but the card still needs SOMETHING to show if Gemini is
    # down. This stitches together whatever fields we did manage to
    # extract into a plain, readable line - not fancy, just functional.
    parts = []
    if fields.get("skill"):
        parts.append(fields["skill"])
    if fields.get("location") and fields["location"] != "Unknown":
        parts.append(fields["location"])
    if fields.get("experience_years"):
        parts.append(f"{fields['experience_years']} saal ka tajurba")
    if fields.get("rate_info"):
        parts.append(fields["rate_info"])
    if fields.get("working_hours"):
        parts.append(fields["working_hours"])
    return " - ".join(parts) if parts else None


def extract_fields(text):
    # main entry point - everything above funnels into this one dict shape
    entry_type = extract_type(text)
    skill, category, secondary_skills = extract_skill_and_category_detailed(text)
    location = extract_location(text)
    experience = extract_experience_years(text)
    rate_info = extract_rate_info(text)
    working_hours = extract_working_hours(text)

    fields = {
        "type": entry_type,
        "category": category,
        "skill": skill,
        "secondary_skills": secondary_skills,
        "location": location,
        "experience_years": experience,
        "rate_info": rate_info,
        "working_hours": working_hours,
        "raw_text": text,
    }
    # not a real natural-language summary like the LLM produces, but
    # better than a blank card if Gemini is unavailable
    fields["description"] = build_fallback_description(fields)
    return fields


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python src/extraction.py "some Urdu or Roman Urdu text"')
        sys.exit(1)

    input_text = sys.argv[1]
    result = extract_fields(input_text)

    print("\n--- EXTRACTED FIELDS ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("------------------------")