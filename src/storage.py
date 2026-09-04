"""
src/storage.py
----------------
Step 4: Storage

Keeps two simple JSON "databases" — one for workers, one for employers.
No SQL, no server — just JSON files that we read/write to. This is
intentionally simple: fine for a hackathon-scale marketplace (dozens to
low hundreds of entries), and easy to inspect/debug by just opening the
file.

Files used:
    data/workers.json    <- all worker entries
    data/employers.json  <- all employer entries

Usage (standalone test):
    python src/storage.py
"""

import json
import os
import uuid
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SEED_FILE = os.path.join(DATA_DIR, "seed_data.json")
WORKERS_FILE = os.path.join(DATA_DIR, "workers.json")
EMPLOYERS_FILE = os.path.join(DATA_DIR, "employers.json")


# ---------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------

def _load_json(path: str) -> list:
    """Read a JSON file and return a list. Returns [] if file is empty/missing."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return []
        return json.loads(content)


def _save_json(path: str, data: list):
    """Write a list back to a JSON file, pretty-printed, UTF-8 (Urdu-safe)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalize_entry(entry: dict) -> dict:
    """
    IMPORTANT FIX: generate_seed_data.py stores the worker/employer's
    trade under the key "role" (e.g. role="Electrician"), while the
    extraction pipeline (llm_extraction.py) produces the key "skill"
    for the same concept. If matching.py or the UI only reads one of
    these keys, seed data and live-extracted entries silently stop
    being comparable — no crash, just wrong/missing matches.

    This function makes both keys always available and always in sync,
    no matter which one the entry originally had. Called on every
    load and every add, so nothing downstream needs to guess which
    field name is present.
    """
    entry = dict(entry)  # don't mutate caller's dict
    skill_val = entry.get("skill")
    role_val = entry.get("role")

    if skill_val and not role_val:
        entry["role"] = skill_val
    elif role_val and not skill_val:
        entry["skill"] = role_val
    # if both present (or both missing), leave as-is — nothing to reconcile

    return entry


def _normalize_all(entries: list) -> list:
    return [_normalize_entry(e) for e in entries]


def _file_for_type(entry_type: str) -> str:
    """Resolve the correct JSON file path for 'worker' or 'employer'."""
    return WORKERS_FILE if entry_type == "worker" else EMPLOYERS_FILE


def _find_and_update(entry_type: str, entry_id: str, updater) -> bool:
    """
    Shared helper for the single-field update functions below
    (update_status, increment_applicant_count, update_availability,
    mark_reported). Loads the correct file, finds the entry by id,
    applies `updater` (a function that mutates the entry dict in
    place), saves if found.

    Returns True if the entry was found and updated, False otherwise
    (so the UI can tell the user "entry not found" instead of
    silently doing nothing).
    """
    path = _file_for_type(entry_type)
    data = _load_json(path)
    found = False
    for entry in data:
        if entry.get("id") == entry_id:
            updater(entry)
            found = True
            break
    if found:
        _save_json(path, data)
    return found


# ---------------------------------------------------------
# Public API — this is what Step 5 (Matching) and Step 6 (UI) will use
# ---------------------------------------------------------

def load_workers() -> list:
    """Return all worker entries currently stored (skill/role fields normalized)."""
    return _normalize_all(_load_json(WORKERS_FILE))


def load_employers() -> list:
    """Return all employer entries currently stored (skill/role fields normalized)."""
    return _normalize_all(_load_json(EMPLOYERS_FILE))


def add_entry(entry: dict) -> dict:
    """
    Add a new structured entry (from Step 3's extraction output) to the
    correct file, based on its "type" field ("worker" or "employer").

    Input:
        entry: dict with at least a "type" field, e.g. the output of
               extract_fields_smart() from llm_extraction.py

    Output:
        The same entry, but with an "id" and "created_at" field added
        (useful for the UI and for debugging), and "skill"/"role"
        normalized so it matches seed data field naming.

    Raises:
        ValueError if entry["type"] is not "worker" or "employer".
    """
    entry_type = entry.get("type")
    if entry_type not in ("worker", "employer"):
        raise ValueError(f"entry['type'] must be 'worker' or 'employer', got: {entry_type!r}")

    # add tracking fields
    entry = _normalize_entry(entry)  # don't mutate caller's dict (done inside)
    entry.setdefault("id", str(uuid.uuid4())[:8])
    entry.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    entry.setdefault("status", "open")        # new entries always start open
    entry.setdefault("applicant_count", 0)    # nobody has applied/contacted yet
    entry.setdefault("urgent", False)         # employer can flag urgent in app.py

    if entry_type == "worker":
        entry.setdefault("availability", "available")  # "available" | "busy" — voice Availability Toggle
        data = _load_json(WORKERS_FILE)
        data.append(entry)
        _save_json(WORKERS_FILE, data)
    else:
        data = _load_json(EMPLOYERS_FILE)
        data.append(entry)
        _save_json(EMPLOYERS_FILE, data)

    return entry


def update_status(entry_type: str, entry_id: str, new_status: str) -> bool:
    """
    Set an entry's status field ("open" or "filled"). Used by the
    "Job Mil Gaya" employer toggle (PROJECT_REFERENCE Section 6, item
    15) — matching.py is expected to filter out status=="filled"
    entries from results once this is wired into the UI.

    Returns:
        True if the entry was found and updated, False otherwise.

    Raises:
        ValueError if new_status is not "open" or "filled".
    """
    if new_status not in ("open", "filled"):
        raise ValueError(f"new_status must be 'open' or 'filled', got: {new_status!r}")

    def _apply(entry):
        entry["status"] = new_status

    return _find_and_update(entry_type, entry_id, _apply)


def update_availability(entry_type: str, entry_id: str, availability: str) -> bool:
    """
    Set a worker's availability field ("available" or "busy"). Used by
    the voice-based Availability Toggle — worker records a short
    message ("main available hoon" / "main busy hoon"), app.py detects
    the intent, and calls this so employers stop seeing/matching with
    a worker who's currently unavailable (see matching.py's
    _load_open_candidates, which filters on this field).

    Only meaningful for workers, but not hard-restricted to
    entry_type == "worker" here — mirrors update_status's simplicity.

    Returns:
        True if the entry was found and updated, False otherwise.

    Raises:
        ValueError if availability is not "available" or "busy".
    """
    if availability not in ("available", "busy"):
        raise ValueError(f"availability must be 'available' or 'busy', got: {availability!r}")

    def _apply(entry):
        entry["availability"] = availability

    return _find_and_update(entry_type, entry_id, _apply)


def increment_applicant_count(entry_type: str, entry_id: str) -> bool:
    """
    Increment an entry's applicant_count by 1. Used whenever someone
    expresses interest / gets contacted (PROJECT_REFERENCE Section 6,
    item 16 — "3 logon ne dilchaspi zahir ki" display).

    Returns:
        True if the entry was found and updated, False otherwise.
    """
    def _apply(entry):
        entry["applicant_count"] = entry.get("applicant_count", 0) + 1

    return _find_and_update(entry_type, entry_id, _apply)


def mark_reported(entry_type: str, entry_id: str) -> bool:
    """
    Mark an entry as reported (simple safety-net feature). Finds the
    entry by id in the correct file and sets reported=True.

    NOTE: the "Report" button in app.py that would have called this
    was removed (PROJECT_REFERENCE Section 8 — it was non-functional,
    nothing filtered reported entries out of matching). This function
    is currently unused by the rest of the app; kept here in case the
    feature is revisited later, not wired into any caller right now.

    Returns:
        True if the entry was found and updated, False otherwise
        (so the UI can tell the user "entry not found" instead of
        silently doing nothing).
    """
    def _apply(entry):
        entry["reported"] = True

    return _find_and_update(entry_type, entry_id, _apply)


def initialize_from_seed(overwrite: bool = False):
    """
    Split seed_data.json into workers.json / employers.json.
    Run this ONCE at project setup (or with overwrite=True to reset
    the live database back to the original seed data).
    """
    if not overwrite and (os.path.exists(WORKERS_FILE) or os.path.exists(EMPLOYERS_FILE)):
        existing_workers = len(load_workers())
        existing_employers = len(load_employers())
        if existing_workers or existing_employers:
            print(f"[storage] workers.json ({existing_workers}) / employers.json "
                  f"({existing_employers}) already have data — skipping. "
                  f"Pass overwrite=True to reset.")
            return

    seed = _load_json(SEED_FILE)
    if not seed:
        print(f"[storage] No seed data found at {SEED_FILE}")
        return

    workers = [e for e in seed if e.get("type") == "worker"]
    employers = [e for e in seed if e.get("type") == "employer"]

    # give seed entries created_at too, for consistency
    now = datetime.now(timezone.utc).isoformat()
    for e in workers + employers:
        e.setdefault("created_at", now)
        e.setdefault("urgent", False)
    for e in workers:
        e.setdefault("availability", "available")

    _save_json(WORKERS_FILE, workers)
    _save_json(EMPLOYERS_FILE, employers)

    print(f"[storage] Initialized: {len(workers)} workers, {len(employers)} employers.")


# ---------------------------------------------------------
# Standalone test — run this file directly to set up the database
# ---------------------------------------------------------
if __name__ == "__main__":
    print("Initializing database from seed_data.json...")
    initialize_from_seed()

    print(f"\nTotal workers now:   {len(load_workers())}")
    print(f"Total employers now: {len(load_employers())}")

    # quick demo: add one live entry, like Step 3 would produce
    demo_entry = {
        "type": "worker",
        "category": "tradesman",
        "skill": "Electrician",
        "location": "Gulshan-e-Iqbal",
        "experience_years": 7,
        "raw_text": "main gulshan mein rehta hoon wiring ka kaam saat saal se karta hoon",
        "extraction_method": "demo_test",
    }
    saved = add_entry(demo_entry)
    print(f"\nAdded a demo entry with id: {saved['id']}")
    print(f"  -> saved['skill'] = {saved.get('skill')!r}")
    print(f"  -> saved['role']  = {saved.get('role')!r}  (auto-mirrored, for seed-data compatibility)")
    print(f"  -> saved['status'] = {saved.get('status')!r}")
    print(f"  -> saved['applicant_count'] = {saved.get('applicant_count')!r}")
    print(f"  -> saved['urgent'] = {saved.get('urgent')!r}")
    print(f"  -> saved['availability'] = {saved.get('availability')!r}")
    print(f"Total workers now:   {len(load_workers())}")

    # quick demo: exercise the update functions on the entry just added
    ok1 = increment_applicant_count("worker", saved["id"])
    ok2 = increment_applicant_count("worker", saved["id"])
    ok3 = update_status("worker", saved["id"], "filled")
    ok4 = update_availability("worker", saved["id"], "busy")
    print(f"\nincrement_applicant_count called twice -> both succeeded: {ok1 and ok2}")
    print(f"update_status to 'filled' -> succeeded: {ok3}")
    print(f"update_availability to 'busy' -> succeeded: {ok4}")

    updated = [e for e in load_workers() if e["id"] == saved["id"]][0]
    print(f"  -> final applicant_count = {updated.get('applicant_count')!r} (expect 2)")
    print(f"  -> final status          = {updated.get('status')!r} (expect 'filled')")
    print(f"  -> final availability    = {updated.get('availability')!r} (expect 'busy')")

    ok_missing = update_status("worker", "no-such-id-xyz", "filled")
    print(f"\nupdate_status on non-existent id -> returns False: {ok_missing is False}")