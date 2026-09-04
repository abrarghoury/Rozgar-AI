# File: src/llm_extraction.py
# Description: Gemini-based "smart" extractor. Sends transcript to Gemini,
# gets structured JSON back. Falls back to extraction.py (rule-based) on
# any failure. Tries multiple Gemini model name candidates since Google
# renames/retires model strings over time.
#
# Setup: pip install google-generativeai python-dotenv
#        .env needs: GEMINI_API_KEY=your_key_here
#
# Usage: python src/llm_extraction.py "main gulshan mein rehta hoon AC fitting ka kaam panch saal se karta hoon"

import os
import sys
import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from dotenv import load_dotenv
from google import genai
from google.genai import types

try:
    from src.extraction import extract_fields as extract_fields_rule_based
except ImportError:
    from extraction import extract_fields as extract_fields_rule_based

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")

# Tried in order. If one is retired/renamed, next candidate is used automatically.
# Google retired the entire 2.x/1.5 Flash line (all three used to be here)
# in favour of the Gemini 3.x family. generateContent is still fully
# supported for these models (Google's newer "Interactions API" is only
# recommended for new projects, not required), so no other code changes
# were needed - just these model names.
MODEL_CANDIDATES = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-flash-latest",
]

# Max time (seconds) to wait on a single Gemini call before giving up and
# moving to the next model candidate (or to the rule-based fallback).
# Without this, a slow/hanging network call can block the whole
# Streamlit app indefinitely, which is what was causing the "connection
# out" issue — the client-side websocket times out on the user's end
# while the server is still stuck waiting on Gemini with no limit.
#
# NOTE: this is implemented with a plain Python thread timeout below
# (see _call_gemini_with_timeout), NOT via genai.Client(http_options=...).
# That SDK-level parameter's accepted shape differs across
# google-genai versions, and passing the wrong shape can make client
# creation itself misbehave — which silently breaks EVERY Gemini call
# and makes it look like "Gemini always fails". A thread-based timeout
# works the same way regardless of SDK version.
GEMINI_TIMEOUT_SECONDS = 15

_client = genai.Client(api_key=API_KEY) if API_KEY else None

# One small worker pool reused across calls, instead of spinning up a
# new thread every time.
_executor = ThreadPoolExecutor(max_workers=4)

# Caches last working model name so we don't re-scan candidates every call.
_working_model_name = None

# Schema must match extraction.py's output shape (rest of app doesn't
# care which extractor produced the data). rate_info/working_hours are
# free text on purpose - see PROJECT_REFERENCE.md Section 4.
SYSTEM_PROMPT = """You are a data extraction engine for a Pakistani job marketplace called Rozgar AI.
You will receive a transcript of a short Urdu voice note from a worker or an employer in Karachi.

Extract the following fields and return ONLY a valid JSON object, nothing else - no markdown,
no explanation, no code fences.

Fields to extract:
- "type": either "worker" (someone describing their own skill/availability) or "employer"
  (someone asking for a worker). Employers usually say things like "chahiye" / "zarurat hai".
- "category": one of "tradesman" (electrician, plumber, AC technician, mechanic, carpenter,
  painter, welder), "home_based_woman" (tailor/darzan, home tutor, embroidery, cook/chef), or
  "bulk_staffing" (security guard, construction labour, domestic helper, driver, loader,
  gardener, cleaner, delivery boy). Use null if unclear.
- "skill": the specific role/skill in English, e.g. "Electrician", "AC Technician",
  "Tailoring / Darzan", "Home Tutor", "Security Guard", "Cook / Chef", "Gardener", "Cleaner",
  "Delivery Boy". If the speaker mentions more than one skill (e.g. "AC fitting aur wiring"),
  use whichever is mentioned FIRST / is the main subject of the sentence, not a secondary
  detail. Use null if unclear.
- "secondary_skills": array of any OTHER skills also mentioned besides the primary one
  (e.g. ["Electrician"] if they also mentioned wiring alongside their main AC Technician
  skill). Empty array if none.
- "location": the Karachi neighbourhood mentioned (e.g. "Gulshan-e-Iqbal", "Korangi",
  "North Nazimabad", "Lyari", "Landhi", "Malir"). Correct obvious transcription typos to the
  real neighbourhood name. Use "Unknown" if no location is mentioned.
- "experience_years": integer number of years of experience if mentioned, else null.
- "rate_info": if any pay, price, or salary figure is mentioned, copy out that part of the
  sentence as plain text, in the language/script it was said in - do NOT try to reduce it to
  a single number. A tailor might quote two different prices for two different items
  ("sada suit 500 rupees, design wala 1200 rupees") - keep both. Use null if no pay/rate
  is mentioned at all.
- "working_hours": if working hours, shift, or timing is mentioned (e.g. "8 ghante", "night
  shift"), copy that part out as plain text. Use null if not mentioned.
- "description": a short (one sentence) natural description of what the work involves, in
  Urdu script, written the way you'd describe it to someone browsing job listings. Base it
  only on what's actually in the transcript - do not invent details that weren't said.

Respond with ONLY the JSON object in this exact shape:
{"type": "...", "category": "...", "skill": "...", "secondary_skills": [...], "location": "...",
 "experience_years": ..., "rate_info": "...", "working_hours": "...", "description": "..."}
"""


def _parse_json_response(raw_text):
    # Gemini sometimes wraps JSON in code fences even when told not to.
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```json\s*|^```\s*|```$", "", cleaned, flags=re.MULTILINE).strip()
    return json.loads(cleaned)


def _call_gemini(model_name, text):
    response = _client.models.generate_content(
        model=model_name,
        contents=text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            # We don't use tools/function-calling here, so explicitly
            # disable Automatic Function Calling. Without this the SDK
            # prints an unrelated "Direct use of AFC..." warning on
            # every call, which has nothing to do with real failures
            # but clutters the logs and makes actual errors harder to spot.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return _parse_json_response(response.text)


def _call_gemini_with_timeout(model_name, text):
    # Runs the (blocking) Gemini call on a worker thread and gives up
    # after GEMINI_TIMEOUT_SECONDS, instead of waiting on it forever.
    future = _executor.submit(_call_gemini, model_name, text)
    try:
        return future.result(timeout=GEMINI_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        raise TimeoutError(
            f"Gemini call to '{model_name}' took longer than {GEMINI_TIMEOUT_SECONDS}s."
        )


def extract_fields_llm(text):
    # Tries MODEL_CANDIDATES in order, caches the working one. Re-scans
    # if the cached model starts failing. Raises only if all fail.
    global _working_model_name

    if not _client:
        raise RuntimeError("GEMINI_API_KEY not found in .env - cannot call Gemini.")

    ordered_candidates = MODEL_CANDIDATES.copy()
    if _working_model_name and _working_model_name in ordered_candidates:
        ordered_candidates.remove(_working_model_name)
        ordered_candidates.insert(0, _working_model_name)

    last_error = None
    all_errors = []
    for model_name in ordered_candidates:
        try:
            parsed = _call_gemini_with_timeout(model_name, text)
            _working_model_name = model_name
            return {
                "type": parsed.get("type"),
                "category": parsed.get("category"),
                "skill": parsed.get("skill"),
                "secondary_skills": parsed.get("secondary_skills") or [],
                "location": parsed.get("location", "Unknown"),
                "experience_years": parsed.get("experience_years"),
                "rate_info": parsed.get("rate_info"),
                "working_hours": parsed.get("working_hours"),
                "description": parsed.get("description"),
                "raw_text": text,
                "model_used": model_name,
            }
        except Exception as e:
            last_error = e
            all_errors.append(f"{model_name}: {e}")
            print(f"[llm_extraction] Candidate '{model_name}' failed: {e}")
            continue

    raise RuntimeError(
        "All Gemini model candidates failed.\n" + "\n".join(all_errors)
    )


def extract_fields_smart(text):
    # Main entry point. Tries Gemini first, falls back to rule-based
    # silently on any failure. "extraction_method" tells you which path ran.
    try:
        result = extract_fields_llm(text)
        result["extraction_method"] = "gemini"
        return result
    except Exception as e:
        print(f"[llm_extraction] Gemini failed on all candidate models ({e}) - falling back to rule-based.")
        result = extract_fields_rule_based(text)
        result["extraction_method"] = "rule_based_fallback"
        result["model_used"] = None  # keep schema identical to the gemini-path result
        return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python src/llm_extraction.py "some Urdu or Roman Urdu text"')
        sys.exit(1)

    input_text = sys.argv[1]
    result = extract_fields_smart(input_text)

    print("\n--- EXTRACTED FIELDS ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("------------------------")