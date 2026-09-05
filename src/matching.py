"""
src/matching.py
-----------------
Step 5: Matching Engine

Given a new entry (a worker looking for a job, or an employer looking
for a worker), find the best matches from the OPPOSITE side of the
marketplace and rank them.

HOW SCORING WORKS (no GPS, no maps API -- see locations.py):

    Final Score = (Location Score x W_loc) + (Skill Score x W_skill)
                  + (Experience Score x W_exp)

    The weights (W_loc, W_skill, W_exp) depend on the entry's CATEGORY,
    because "closeness matters" differently per category:

        home_based_woman -> Location 0.6, Skill 0.4, Experience 0.0
            (a tutor/tailor's customers come TO them, so distance
            matters most; experience isn't weighted separately here
            since it's already implicit in how a tutor/tailor
            describes themselves)

        tradesman         -> Location 0.3, Skill 0.5, Experience 0.2
            (electricians/plumbers travel to the job, so skill match
            matters most, but a nearer worker is still preferred and
            more years of experience nudges the ranking up)

        bulk_staffing      -> Location 0.2, Skill 0.5, Experience 0.3
            (guards/labour are mobile and jobs are often urgent, so
            skill fit and experience matter more than exact proximity)

    If experience data isn't available on one side (e.g. an employer
    listing that didn't specify required experience), the experience
    weight is redistributed proportionally into location + skill
    instead of just being dropped — so the three weights per category
    always add up to a meaningful total either way.

    Location Score (from locations.py):
        same area           -> 1.0
        same district        -> 0.6
        different district    -> 0.3

    Skill Score (this file, tiered):
        exact skill match                     -> 1.0
        related skill (explicit list, e.g.
          Electrician <-> AC Technician)        -> 0.7
        same category, different skill          -> embedding score, capped at 0.5
        different category entirely              -> embedding score, capped at 0.25
        (the embedding similarity itself comes from a multilingual
        sentence-transformer model, so differently-worded Urdu/Roman
        Urdu descriptions of the same skill still score highly)

    Experience Score (this file):
        difference of 0 years   -> 1.0
        difference of 1-2 years  -> 0.8
        difference of 3-5 years  -> 0.5
        difference of 6+ years   -> 0.2

RELEVANCE GATE (real-world result quality fix — see below):
    With location weighted heavily in some categories (esp. tradesman
    when experience data is missing), a same-area candidate with a
    totally unrelated skill (e.g. a Driver listing) could still land a
    "not weak" score for an Electrician search, purely from proximity.
    That's a poor result for a real dashboard — an Electrician
    shouldn't see Driver jobs ranked above genuinely relevant ones.

    Fix: candidates are split into a RELEVANT pool (skill_score >= 0.5,
    i.e. exact/related/same-category matches) and a CATEGORY-RESTRICTED
    FALLBACK pool. Results are filled from the relevant pool first;
    fallback candidates only appear if the relevant pool has fewer than
    top_n entries -- so the "never show an empty screen" guarantee
    (PROJECT_REFERENCE Section 5.6) still holds, but only kicks in when
    there's genuinely nothing more relevant nearby.

    IMPORTANT (category restriction on fallback): the fallback pool is
    restricted to candidates in the SAME broad category as new_entry
    (e.g. a Carpenter search can fall back to another tradesman like a
    Painter or Electrician, since skill_score's "same category, capped
    at 0.5" tier already covers this). Candidates from a COMPLETELY
    DIFFERENT category (e.g. a Darzan/home_based_woman or a Security
    Guard/bulk_staffing showing up for a Carpenter/tradesman search)
    are dropped entirely -- they are never appended to either pool, no
    matter how close geographically or how few relevant results exist.
    A same-area-but-wrong-trade result is a reasonable "closest
    available" substitute; a different-category one isn't. In practice
    this means find_matches() can now legitimately return FEWER than
    top_n results (even zero) if that's genuinely all there is in the
    same category -- that's intentional and more honest than padding
    the list with irrelevant candidates just to hit a fixed count.

Only "open" listings are matched against — entries with status=="filled"
are excluded from the candidate pool before scoring even starts (an
employer who already found someone, or a worker no longer available,
shouldn't keep showing up in results).

The engine does NOT force a fixed result count just to avoid an empty
screen -- it returns the best available OPEN, SAME-CATEGORY candidates,
ranked, and lets the list be shorter than top_n (or empty) when that's
genuinely all there is. Each result is flagged with "is_weak_match" so
the UI can show an honest "closest available" message instead of
presenting a poor match as if it were a great one.

Usage (standalone test):
    python src/matching.py
"""

import sys

# NOTE: sentence-transformers is imported LAZILY inside get_model(),
# not here at the top of the file. Importing it at module load time
# would pull in the whole transformers/torch stack immediately when
# app.py starts — so if anything in that heavy dependency chain has
# an issue (e.g. a missing torchvision submodule), the ENTIRE app
# would crash before Streamlit even renders a single pixel. Loading
# it lazily means the UI, mic recording, and transcript editing all
# work fine regardless — only the matching step depends on it.

# Works both when this file is run directly (python src/matching.py)
# and when imported as a package member (from src.matching import ...),
# e.g. from app.py.
try:
    from src.storage import load_workers, load_employers, _normalize_entry
    from src.locations import location_proximity_score
except ImportError:
    from storage import load_workers, load_employers, _normalize_entry
    from locations import location_proximity_score

# ---------------------------------------------------------
# Load the embedding model once (this is slow — a few seconds — so we
# do it a single time when first needed, not on every match).
# Multilingual model: handles Urdu script, Roman Urdu, and English.
# ---------------------------------------------------------
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model = None

# ---------------------------------------------------------
# Category-specific weights. Keys must sum to 1.0 (not strictly
# enforced, but keep them that way for scores to stay in 0..1 range).
# A category not listed here (or None/unknown) falls back to
# DEFAULT_WEIGHTS, an even split with no separate experience factor.
# ---------------------------------------------------------
CATEGORY_WEIGHTS = {
    "tradesman":         {"location": 0.3, "skill": 0.5, "experience": 0.2},
    "home_based_woman":  {"location": 0.6, "skill": 0.4, "experience": 0.0},
    "bulk_staffing":      {"location": 0.2, "skill": 0.5, "experience": 0.3},
}
DEFAULT_WEIGHTS = {"location": 0.5, "skill": 0.5, "experience": 0.0}

# Below this final score, a match is flagged as "weak" so the UI can
# show it honestly (e.g. "closest available, not an exact match")
# rather than presenting it with the same confidence as a strong match.
# Raised from 0.4 to 0.45 alongside the relevance gate below — with the
# gate now keeping unrelated-skill candidates out of normal results,
# this threshold mainly catches genuine "best available, still not
# great" fallback cases (weak location + weak skill fallback matches).
WEAK_MATCH_THRESHOLD = 0.45

# Minimum skill_score for a candidate to count as "relevant" rather
# than a same-area-but-wrong-trade fallback. 0.5 is exactly the
# same-category cap, so this admits exact matches (1.0), related
# matches (0.7), and same-category matches (<=0.5), while excluding
# different-category matches (capped at 0.25) from the primary pool.
RELEVANCE_SKILL_THRESHOLD = 0.5

# ---------------------------------------------------------
# Related-skills tier (PROJECT_REFERENCE Section 5.3). Pairs of skills
# that are close enough in real-world overlap that a worker/employer
# matching on one but not the other should still score meaningfully
# higher than an unrelated same-category match (e.g. Welder), but not
# as high as an exact match. Kept as an explicit, curated list rather
# than derived from embeddings — embedding similarity alone was the
# original problem (unrelated trades scoring too close to real matches
# just from similar sentence phrasing), so this tier deliberately does
# NOT use embeddings.
#
# Stored one-directional per pair below; RELATED_SKILLS is built as a
# symmetric lookup (A->B implies B->A) so callers don't need to check
# both orders.
_RELATED_SKILL_PAIRS = [
    ("Electrician", "AC Technician"),        # both involve household wiring/fitting
    ("Plumber", "AC Technician"),             # both do pipe/line fitting work
    ("Carpenter", "Painter"),                 # commonly hired together for finishing work
    ("Auto Mechanic", "Bike Mechanic"),       # same skillset, different vehicle type
    ("Construction Labour", "Loader / Helper"),  # overlapping general-labour tasks
    ("Domestic Helper", "Cleaner"),           # overlapping household-cleaning tasks
    ("Gardener", "Cleaner"),                  # often the same general outdoor-helper role
]

RELATED_SKILLS = {}
for _a, _b in _RELATED_SKILL_PAIRS:
    RELATED_SKILLS.setdefault(_a, set()).add(_b)
    RELATED_SKILLS.setdefault(_b, set()).add(_a)


def get_model():
    """
    Load the multilingual sentence-transformer model once and reuse it.

    Streamlit-safe: when running inside Streamlit, this uses
    st.cache_resource so the model is loaded exactly once per app
    process (not re-loaded on every rerun/button-click, which is what
    was making save/search feel slow after deployment). When Streamlit
    isn't available (e.g. running this file standalone from the
    command line), it falls back to plain global-variable caching —
    same pattern used in speech_to_text.py's get_model_cached().
    """
    global _model
    try:
        import streamlit as st
    except ImportError:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            print(f"[matching] Loading embedding model '{_MODEL_NAME}'...")
            _model = SentenceTransformer(_MODEL_NAME)
            print("[matching] Model loaded.")
        return _model

    @st.cache_resource
    def _load_cached():
        from sentence_transformers import SentenceTransformer
        print(f"[matching] Loading embedding model '{_MODEL_NAME}' (cached)...")
        return SentenceTransformer(_MODEL_NAME)

    return _load_cached()


def _text_for_embedding(entry: dict) -> str:
    """
    Build the text we'll embed for similarity comparison. Combining
    skill + category + raw_text gives the embedding model more signal
    than raw_text alone (which may be short or noisy from Whisper).
    """
    parts = [
        entry.get("skill") or "",
        entry.get("category") or "",
        entry.get("raw_text") or entry.get("text") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def _is_related_skill(skill_a: str, skill_b: str) -> bool:
    """Case-insensitive check against the curated RELATED_SKILLS list."""
    # normalize casing to match the canonical names used as dict keys
    for a, related_set in RELATED_SKILLS.items():
        if a.lower() == skill_a:
            return any(r.lower() == skill_b for r in related_set)
    return False


def _skill_similarity_score(new_entry: dict, candidate: dict, embedding_score: float) -> float:
    """
    Tiered skill scoring — much more discriminating than raw embedding
    similarity alone, which was letting unrelated trades (e.g. Welder)
    score almost as high as genuine matches (e.g. Electrician) just
    because the surrounding sentence phrasing was similar.

    Tiers:
        exact skill match (e.g. "Electrician" == "Electrician")   -> 1.0
        related skill (explicit curated list, e.g. Electrician
          <-> AC Technician)                                       -> 0.7
        same category, different skill (both "tradesman")          -> embedding score, capped at 0.5
        different category entirely                                 -> embedding score, capped at 0.25
    """
    new_skill = (new_entry.get("skill") or "").strip().lower()
    cand_skill = (candidate.get("skill") or "").strip().lower()
    new_category = new_entry.get("category")
    cand_category = candidate.get("category")

    if new_skill and new_skill == cand_skill:
        return 1.0
    if new_skill and cand_skill and _is_related_skill(new_skill, cand_skill):
        return 0.7
    if new_category and new_category == cand_category:
        return min(embedding_score, 0.5)
    return min(embedding_score, 0.25)


def _experience_score(new_entry: dict, candidate: dict):
    """
    Score how close two entries' years of experience are.

    Returns:
        A float in [0, 1] if BOTH sides have an experience_years value,
        or None if either side is missing it (e.g. most employer
        listings don't specify a number) — callers should treat None
        as "not applicable" and redistribute this factor's weight
        elsewhere, not treat it as a score of 0.
    """
    new_exp = new_entry.get("experience_years")
    cand_exp = candidate.get("experience_years")
    if new_exp is None or cand_exp is None:
        return None

    diff = abs(new_exp - cand_exp)
    if diff == 0:
        return 1.0
    elif diff <= 2:
        return 0.8
    elif diff <= 5:
        return 0.5
    else:
        return 0.2


def _get_weights(category):
    """Look up category weights, falling back to an even default split."""
    return CATEGORY_WEIGHTS.get(category, DEFAULT_WEIGHTS)


def _combine_scores(loc_score: float, skill_score: float, exp_score, weights: dict):
    """
    Combine location/skill/experience into one final score using the
    given category weights. If exp_score is None (experience data not
    available on one side), its weight is redistributed proportionally
    into location + skill instead of just being silently dropped —
    that way a category that leans heavily on experience doesn't end
    up under-weighted overall just because one listing didn't mention
    a number.
    """
    w_loc, w_skill, w_exp = weights["location"], weights["skill"], weights["experience"]

    if exp_score is None or w_exp == 0:
        remaining = w_loc + w_skill
        if remaining == 0:  # degenerate config safety net, shouldn't normally happen
            remaining = 1.0
        w_loc_eff = w_loc + (w_loc / remaining) * w_exp
        w_skill_eff = w_skill + (w_skill / remaining) * w_exp
        return (loc_score * w_loc_eff) + (skill_score * w_skill_eff)

    return (loc_score * w_loc) + (skill_score * w_skill) + (exp_score * w_exp)


def _load_open_candidates(entry_type: str) -> list:
    """
    Load workers or employers, excluding anything status=="filled" —
    a filled listing shouldn't keep appearing in match results
    (PROJECT_REFERENCE Section 6, item 15). Entries with no "status"
    key at all (shouldn't happen post storage.py update, but defensive
    for older/hand-crafted data) are treated as open.
    """
    loader = load_employers if entry_type == "worker" else load_workers
    return [c for c in loader() if c.get("status", "open") != "filled"]


def find_matches(new_entry: dict, top_n: int = 5) -> list:
    """
    Find the best matches for new_entry from the opposite side of the
    marketplace (open listings only — see _load_open_candidates).

    Results are relevance-gated: candidates whose skill is unrelated to
    new_entry's skill (skill_score < RELEVANCE_SKILL_THRESHOLD) are only
    used to fill out the list if there aren't enough relevant candidates
    to reach top_n, AND ONLY if they're in the same broad category as
    new_entry -- see module docstring "RELEVANCE GATE" for why. A
    candidate from a completely different category (e.g. a Darzan
    turning up for a Carpenter search) is never included, regardless of
    how few relevant/fallback results exist.

    Input:
        new_entry: a structured entry (worker or employer), e.g. output
                   of extract_fields_smart() from llm_extraction.py
        top_n: how many ranked matches to return (may return fewer, or
               zero, if that's genuinely all there is in-category)

    Output:
        List of dicts, each:
            {
              "entry": <candidate>,
              "score": float,
              "location_score": float,
              "skill_score": float,
              "experience_score": float | None,
              "is_weak_match": bool,
            }
        sorted best first (relevant matches before same-category
        fallback matches). May be shorter than top_n, or empty, if
        there aren't enough same-category open candidates -- this is
        intentional (see module docstring); "is_weak_match" tells the
        UI when a result is the best available rather than a
        genuinely strong match.
    """
    # Defensive: make sure "skill"/"role" are in sync even if new_entry
    # came straight from extraction/UI editing rather than through
    # storage.py's own load/add functions (which already normalize).
    new_entry = _normalize_entry(new_entry)

    entry_type = new_entry.get("type")
    if entry_type not in ("worker", "employer"):
        raise ValueError(f"new_entry['type'] must be 'worker' or 'employer', got {entry_type!r}")

    candidates = _load_open_candidates(entry_type)

    if not candidates:
        return []

    model = get_model()
    from sentence_transformers import util

    # Embed the new entry once, and all candidates in one batch call
    # (much faster than embedding one at a time in a loop).
    new_text = _text_for_embedding(new_entry)
    candidate_texts = [_text_for_embedding(c) for c in candidates]

    new_embedding = model.encode(new_text, convert_to_tensor=True)
    candidate_embeddings = model.encode(candidate_texts, convert_to_tensor=True)

    similarity_scores = util.cos_sim(new_embedding, candidate_embeddings)[0]

    weights = _get_weights(new_entry.get("category"))
    new_category = new_entry.get("category")

    relevant_results = []    # skill_score >= RELEVANCE_SKILL_THRESHOLD
    fallback_results = []    # same category, but below the relevance threshold

    for i, candidate in enumerate(candidates):
        raw_embedding_score = float(similarity_scores[i])
        skill_score = _skill_similarity_score(new_entry, candidate, raw_embedding_score)
        loc_score = location_proximity_score(
            new_entry.get("location", "Unknown"),
            candidate.get("location", "Unknown"),
        )
        exp_score = _experience_score(new_entry, candidate)
        final_score = _combine_scores(loc_score, skill_score, exp_score, weights)

        result = {
            "entry": candidate,
            "score": round(final_score, 3),
            "location_score": round(loc_score, 3),
            "skill_score": round(skill_score, 3),
            "experience_score": round(exp_score, 3) if exp_score is not None else None,
            "is_weak_match": final_score < WEAK_MATCH_THRESHOLD,
        }

        if skill_score >= RELEVANCE_SKILL_THRESHOLD:
            relevant_results.append(result)
        elif candidate.get("category") == new_category:
            # Same broad category (e.g. both "tradesman") but an
            # unrelated/different specific skill within it -- an
            # acceptable "closest available" fallback (e.g. a Painter
            # showing up for a Carpenter search when no Carpenter is
            # available nearby).
            fallback_results.append(result)
        # else: candidate is in a COMPLETELY DIFFERENT category (e.g.
        # home_based_woman or bulk_staffing showing up for a tradesman
        # search) -- dropped entirely. Not appended to either pool, no
        # matter how close geographically or how few results remain.
        # A Darzan or Security Guard is never a reasonable substitute
        # for a Carpenter, regardless of proximity.

    relevant_results.sort(key=lambda r: r["score"], reverse=True)
    fallback_results.sort(key=lambda r: r["score"], reverse=True)

    # Fill from relevant pool first; only dip into same-category
    # fallback candidates if relevant results don't reach top_n. The
    # combined list may still be shorter than top_n (or empty) if the
    # same category genuinely doesn't have enough open candidates --
    # that's intentional, see module docstring.
    combined = relevant_results + fallback_results
    return combined[:top_n]


# ---------------------------------------------------------
# Standalone test -- run this file directly to try it out
# ---------------------------------------------------------
if __name__ == "__main__":
    # Test 1: exact skill match baseline - now also proves the
    # relevance gate keeps unrelated-CATEGORY candidates (e.g. Home
    # Tutor, Security Guard) out of results entirely, while same-
    # category-but-different-skill tradesmen (e.g. Welder, Painter)
    # can still appear as an honest fallback if needed.
    test_worker = {
        "type": "worker",
        "category": "tradesman",
        "skill": "Electrician",
        "location": "Korangi",
        "experience_years": 5,
        "raw_text": "main korangi mein rehta hoon, wiring aur electrical fitting ka kaam karta hoon",
    }

    print(f"Finding matches for: {test_worker['skill']} in {test_worker['location']}\n")
    matches = find_matches(test_worker, top_n=5)

    if not matches:
        print("No relevant/same-category employer entries in the database yet.")
    else:
        for i, m in enumerate(matches, 1):
            e = m["entry"]
            weak_tag = "  [WEAK MATCH]" if m["is_weak_match"] else ""
            print(f"{i}. {e.get('skill') or e.get('role')} -- {e.get('location')}  "
                  f"(score={m['score']}, location={m['location_score']}, "
                  f"skill={m['skill_score']}, experience={m['experience_score']}){weak_tag}")
            print(f"   \"{e.get('raw_text')}\"")

    # Test 2: related-skills tier sanity check (not run automatically,
    # printed for eyeballing) -- Electrician vs AC Technician should
    # score skill_score == 0.7, not the embedding-capped 0.5/0.25 tiers.
    print("\n--- related-skill tier check ---")
    ac_score = _skill_similarity_score(
        {"skill": "Electrician", "category": "tradesman"},
        {"skill": "AC Technician", "category": "tradesman"},
        embedding_score=0.55,  # deliberately high, to prove the tier caps it correctly
    )
    print(f"Electrician vs AC Technician skill_score = {ac_score} (expect 0.7)")

    unrelated_score = _skill_similarity_score(
        {"skill": "Electrician", "category": "tradesman"},
        {"skill": "Welder", "category": "tradesman"},
        embedding_score=0.55,
    )
    print(f"Electrician vs Welder (same category, unrelated) skill_score = {unrelated_score} (expect capped at 0.5, i.e. 0.5)")
