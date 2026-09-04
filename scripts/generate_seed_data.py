# scripts/generate_seed_data.py
# Description: Builds demo seed data (data/workers.json, employers.json,
# seed_data.json). Run once at setup, or any time to reset the demo DB.
#
# Area scope: limited to 4 districts (Karachi East, Karachi Central,
# Korangi, Malir) - pulled live from locations.ALLOWED_DISTRICTS so seed
# data and matching.py can never drift out of sync. See PROJECT_REFERENCE
# Section 5.1 for why (density per area too thin across all 20+ areas).
#
# Usage: python scripts/generate_seed_data.py

import json
import random
import os
import sys
from datetime import datetime, timedelta

random.seed(42)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from locations import KARACHI_AREAS, ALLOWED_DISTRICTS

TARGET_DISTRICTS = ALLOWED_DISTRICTS  # single source of truth - see header note
AREAS = [area for area, info in KARACHI_AREAS.items() if info["district"] in TARGET_DISTRICTS]

MALE_NAMES = [
    "Asif", "Nasir", "Kashif", "Rashid", "Imran", "Zahid", "Tariq", "Sajid",
    "Shakeel", "Waqar", "Naeem", "Faisal", "Arshad", "Javed", "Riaz",
    "Mumtaz", "Shahid", "Aslam", "Rafiq", "Younus", "Ilyas", "Bilal",
    "Zubair", "Iftikhar", "Qadir"
]

FEMALE_NAMES = [
    "Shabana", "Rukhsana", "Naseem", "Farhat", "Shazia", "Nasreen",
    "Parveen", "Saima", "Bushra", "Yasmeen", "Robina", "Nighat",
    "Zarina", "Shahida", "Rehana", "Samina", "Tahira", "Kausar",
    "Uzma", "Sadia"
]

BUSINESS_PREFIXES = [
    "Al-Madina", "New", "City", "Karachi", "Al-Falah", "Sitara",
    "Bismillah", "Al-Noor", "Metro", "Elite"
]
BUSINESS_SUFFIXES = [
    "Traders", "Store", "Enterprises", "Electronics", "Textiles",
    "General Store", "Hardware", "Services"
]

# ---------------------------------------------------------
# Role/skill pools per category
# ---------------------------------------------------------

TRADESMEN_SKILLS = [
    ("Electrician", "wiring aur electrical fitting"),
    ("Plumber", "plumbing aur pani ki line ka kaam"),
    ("AC Technician", "AC fitting aur wiring"),
    ("Auto Mechanic", "gari ki mistri ka kaam"),
    ("Bike Mechanic", "motorcycle repairing ka kaam"),
    ("Carpenter", "lakri ka kaam aur furniture banane ka kaam"),
    ("Painter", "ghar aur building ki painting ka kaam"),
    ("Welder", "welding aur grill banane ka kaam"),
]

TRADESMEN_TEMPLATES = [
    "Main {area} mein rehta hoon, {work} {exp} saal se karta hoon.",
    "Mera naam {name} hai, main {area} ka rehne wala hoon, {work} mein {exp} saal ka tajurba hai.",
    "{work} ka kaam karta hoon, {exp} saal se, {area} mein available hoon.",
    "Main {name}, {area} se hoon, {work} karta hoon, ghar aur dukaan dono jagah kaam karta hoon, {exp} saal ho gaye.",
]

TUTOR_SUBJECTS = [
    "Urdu aur Math", "English aur Science", "Quran Nazra", "Math aur Science",
    "Urdu, Math aur English", "Quran aur Islamiyat"
]

HOME_WOMEN_TEMPLATES_TAILOR = [
    "Main ghar pe kapre seeti hoon, {exp} saal ka tajurba hai, {area} mein rehti hoon.",
    "Mera naam {name} hai, main {area} mein rehti hoon aur ghar baithe silai ka kaam karti hoon, {exp} saal se.",
    "Main darzan hoon, bridal aur rozmarra ke kapre seeti hoon, {area} mein, {exp} saal se ye kaam kar rahi hoon.",
]

HOME_WOMEN_TEMPLATES_TUTOR = [
    "Main bachon ko ghar pe {subject} parhati hoon, {area} mein rehti hoon.",
    "Mera naam {name} hai, main {area} mein {subject} ki tuition deti hoon, {exp} saal ka tajurba hai.",
    "Main ghar pe tuition deti hoon, {subject}, Matric tak parhati hoon, {area} mein.",
]

HOME_WOMEN_TEMPLATES_EMBROIDERY = [
    "Main hath ki kashidakari karti hoon, {area} mein rehti hoon, {exp} saal ka kaam hai.",
    "Mera naam {name} hai, main {area} se hoon, kaam aur embroidery ka order ghar pe leti hoon.",
]

HOME_WOMEN_TEMPLATES_COOK = [
    "Main ghar pe khana banati hoon, tiffin service deti hoon, {area} mein rehti hoon, {exp} saal ka tajurba hai.",
    "Mera naam {name} hai, main {area} mein rehti hoon, catering aur tiffin ka kaam karti hoon, {exp} saal se.",
]

BULK_ROLES = [
    ("Security Guard", "guard ki naukri", "M"),
    ("Construction Labour", "mazdoori aur construction ka kaam", "M"),
    ("Domestic Helper", "ghar ka kaam", "F"),
    ("Driver", "driving ka kaam", "M"),
    ("Loader / Helper", "godam mein loading ka kaam", "M"),
    ("Gardener", "baghbani ka kaam", "M"),
    ("Cleaner", "safai ka kaam", "F"),
    ("Delivery Boy", "delivery ka kaam", "M"),
]

BULK_TEMPLATES = [
    "Main {area} mein rehta hoon, {work} karta hoon, {exp} saal ka tajurba hai.",
    "Mera naam {name} hai, {area} se hoon, {work} ke liye available hoon, night shift bhi kar sakta hoon.",
    "Main {work} dhoondh raha hoon, {area} mein rehta hoon, {exp} saal pehle bhi ye kaam kiya hai.",
]
BULK_TEMPLATES_F = [
    "Main {area} mein rehti hoon, {work} karti hoon, {exp} saal ka tajurba hai.",
    "Mera naam {name} hai, {area} se hoon, {work} ke liye available hoon, part-time bhi kar sakti hoon.",
]

# ---------------------------------------------------------
# Employer templates
# ---------------------------------------------------------

EMP_TRADES_TEMPLATES = [
    "Humein {area} mein {skill} chahiye, ghar ka chota sa kaam hai.",
    "Mujhe apni dukaan ke liye {skill} chahiye, {area} mein, jald az jald.",
    "Ghar mein {skill} ki zaroorat hai, {area} area mein rehte hain, tajurba kar wala chahiye.",
]

EMP_HOME_WOMEN_TEMPLATES_TAILOR = [
    "Mujhe {area} mein ghar ke liye darzan chahiye, bridal kapre silwane hain.",
    "Humein ek tailor chahiye jo ghar pe silai kare, {area} mein rehte hain.",
]
EMP_HOME_WOMEN_TEMPLATES_TUTOR = [
    "Mujhe apne bachon ke liye home tutor chahiye, {subject}, {area} mein rehte hain.",
    "Humein {area} mein ek tutor chahiye jo ghar aa kar bachon ko parhaye, {subject}.",
]
EMP_HOME_WOMEN_TEMPLATES_COOK = [
    "Mujhe {area} mein ghar ke liye cook chahiye, roz ka khana banane wali chahiye.",
    "Humein tiffin service ke liye cook chahiye, {area} mein rehte hain.",
]

EMP_BULK_TEMPLATES = [
    "Humein apni factory ke liye {count} security guards chahiye, {area} mein, night shift.",
    "Mujhe construction site ke liye {count} mazdoor chahiye, {area} mein, turant zaroorat hai.",
    "Humein ghar ke liye ek domestic helper chahiye, {area} mein rehte hain, full-time.",
    "Mujhe apni dukaan ke liye ek driver chahiye, {area} se, gari chalane ka tajurba ho.",
    "Humein godam ke liye {count} loaders chahiye, {area} mein, roz ka kaam hai.",
]

# ---------------------------------------------------------
# Rate / hours generators - one function per pay pattern, not one
# generic function, because how different trades get paid genuinely
# differs (per-job vs monthly vs per-item). Free text on output, same
# reasoning as extraction.py: never forced into a single number.
# ---------------------------------------------------------

def random_tradesman_rate():
    amt = random.choice([300, 400, 500, 600, 800, 1000, 1500])
    return f"{amt} rupees per kaam"

def random_bulk_salary():
    amt = random.choice([18000, 20000, 22000, 25000, 28000, 30000, 32000])
    return f"{amt} rupees mahana"

def random_tailor_rate():
    # tailors commonly quote different prices per garment type - this
    # is exactly the case that made us keep rate_info as free text
    # instead of one number
    sada = random.choice([400, 500, 600, 700])
    design = random.choice([1000, 1200, 1500, 1800])
    return f"sada suit {sada} rupees, design wala {design} rupees"

def random_tutor_rate():
    amt = random.choice([5000, 6000, 8000, 10000, 12000])
    return f"{amt} rupees per month"

def random_cook_rate():
    amt = random.choice([8000, 10000, 12000, 15000])
    return f"{amt} rupees mahana tiffin service"

def random_embroidery_rate():
    amt = random.choice([300, 500, 800, 1200])
    return f"kaam ke hisaab se {amt} rupees se shuru"

def random_bulk_hours():
    return random.choice([
        "8 ghante subah ki shift",
        "8 ghante night shift",
        "12 ghante ki shift",
        "din mein 10 ghante",
    ])

def random_tutor_hours():
    return random.choice([
        "roz 1 ghanta",
        "hafte mein 5 din, 1 ghanta roz",
        "roz 2 ghante",
    ])

def random_created_at():
    # Staggered so "posted X ago" isn't identical across every entry -
    # spread across the last 30 days. Absolute value isn't reproducible
    # run-to-run (based on datetime.now()), but that's fine: this only
    # feeds a relative "X ago" display, not the matching score.
    minutes_ago = random.randint(5, 30 * 24 * 60)
    return (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()

def build_description(role, area, exp, rate_info, working_hours):
    # same idea as extraction.py's fallback description builder - plain
    # concatenation, not natural language generation, since this is
    # synthetic seed data, not a real transcript
    parts = [role, area]
    if exp:
        parts.append(f"{exp} saal ka tajurba")
    if rate_info:
        parts.append(rate_info)
    if working_hours:
        parts.append(working_hours)
    return " - ".join(parts)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def used_names(pool, n):
    return random.sample(pool, n) if n <= len(pool) else [random.choice(pool) for _ in range(n)]

def generate_phone():
    prefix = random.choice(["300", "301", "302", "303", "312", "321", "333", "345"])
    number = random.randint(1000000, 9999999)
    return f"03{prefix[1:]}-{number}"

def generate_employer_name(is_household):
    if is_household:
        return random.choice(MALE_NAMES + FEMALE_NAMES)
    prefix = random.choice(BUSINESS_PREFIXES)
    suffix = random.choice(BUSINESS_SUFFIXES)
    return f"{prefix} {suffix}"

entries = []
entry_id = 1

def add_entry(etype, category, role, sub_skill, area, exp, text, rate_info=None,
              working_hours=None, extra=None):
    global entry_id
    description = build_description(role, area, exp, rate_info, working_hours)
    e = {
        "id": f"E{entry_id:03d}",
        "type": etype,                 # "worker" or "employer"
        "category": category,          # "tradesman" | "home_based_woman" | "bulk_staffing"
        "role": role,
        "location": area,
        "raw_text": text,
        "phone": generate_phone(),
        "secondary_skills": [],        # seed data doesn't simulate the multi-skill case, kept for schema consistency with live entries
        "rate_info": rate_info,
        "working_hours": working_hours,
        "description": description,
        "status": "open",              # "open" | "filled" - toggled by employer once a worker is found
        "applicant_count": 0,          # filled in below after entry creation
        "urgent": False,               # only meaningful for employer listings
        "created_at": random_created_at(),
    }
    if etype == "worker":
        e["experience_years"] = exp
    if extra:
        e.update(extra)
    entries.append(e)
    entry_id += 1

# ---------------- WORKERS: Tradesmen (18) ----------------
names_pool = used_names(MALE_NAMES, 18)
for i in range(18):
    role, work = random.choice(TRADESMEN_SKILLS)
    area = random.choice(AREAS)
    exp = random.randint(1, 15)
    name = names_pool[i]
    template = random.choice(TRADESMEN_TEMPLATES)
    text = template.format(area=area, work=work, exp=exp, name=name)
    rate = random_tradesman_rate()
    add_entry("worker", "tradesman", role, work, area, exp, text,
              rate_info=rate, working_hours=None, extra={"name": name})

# ---------------- WORKERS: Home-based women (18) ----------------
names_pool = used_names(FEMALE_NAMES, 18)
for i in range(18):
    name = names_pool[i]
    area = random.choice(AREAS)
    exp = random.randint(1, 12)
    sub_choice = random.choices(
        ["tailor", "tutor", "embroidery", "cook"], weights=[8, 7, 2, 3], k=1
    )[0]
    if sub_choice == "tailor":
        template = random.choice(HOME_WOMEN_TEMPLATES_TAILOR)
        text = template.format(area=area, exp=exp, name=name)
        add_entry("worker", "home_based_woman", "Tailoring / Darzan", "silai", area, exp, text,
                  rate_info=random_tailor_rate(), working_hours=None, extra={"name": name})
    elif sub_choice == "tutor":
        subject = random.choice(TUTOR_SUBJECTS)
        template = random.choice(HOME_WOMEN_TEMPLATES_TUTOR)
        text = template.format(area=area, exp=exp, name=name, subject=subject)
        add_entry("worker", "home_based_woman", "Home Tutor", subject, area, exp, text,
                  rate_info=random_tutor_rate(), working_hours=random_tutor_hours(),
                  extra={"name": name, "subjects": subject})
    elif sub_choice == "cook":
        template = random.choice(HOME_WOMEN_TEMPLATES_COOK)
        text = template.format(area=area, exp=exp, name=name)
        add_entry("worker", "home_based_woman", "Cook / Chef", "khana banane", area, exp, text,
                  rate_info=random_cook_rate(), working_hours=None, extra={"name": name})
    else:
        template = random.choice(HOME_WOMEN_TEMPLATES_EMBROIDERY)
        text = template.format(area=area, exp=exp, name=name)
        add_entry("worker", "home_based_woman", "Embroidery / Kasheeda", "kashidakari", area, exp, text,
                  rate_info=random_embroidery_rate(), working_hours=None, extra={"name": name})

# ---------------- WORKERS: Bulk / general staffing (13) ----------------
for i in range(13):
    role, work, gender = random.choice(BULK_ROLES)
    area = random.choice(AREAS)
    exp = random.randint(1, 10)
    if gender == "M":
        name = random.choice(MALE_NAMES)
        template = random.choice(BULK_TEMPLATES)
    else:
        name = random.choice(FEMALE_NAMES)
        template = random.choice(BULK_TEMPLATES_F)
    text = template.format(area=area, work=work, exp=exp, name=name)
    add_entry("worker", "bulk_staffing", role, work, area, exp, text,
              rate_info=random_bulk_salary(), working_hours=random_bulk_hours(),
              extra={"name": name})

# ---------------- EMPLOYERS: Tradesmen (8) ----------------
# no rate_info here - employers asking for a tradesman rarely state a
# budget upfront in these phrasings, that's typically negotiated
for i in range(8):
    role, work = random.choice(TRADESMEN_SKILLS)
    area = random.choice(AREAS)
    template = random.choice(EMP_TRADES_TEMPLATES)
    text = template.format(area=area, skill=role)
    emp_name = generate_employer_name(is_household=random.random() < 0.6)
    add_entry("employer", "tradesman", role, work, area, None, text,
              rate_info=None, working_hours=None, extra={"name": emp_name})

# ---------------- EMPLOYERS: Home-based women (8) ----------------
for i in range(8):
    sub_choice = random.choices(["tailor", "tutor", "cook"], weights=[4, 4, 2], k=1)[0]
    area = random.choice(AREAS)
    emp_name = generate_employer_name(is_household=True)
    if sub_choice == "tailor":
        template = random.choice(EMP_HOME_WOMEN_TEMPLATES_TAILOR)
        text = template.format(area=area)
        add_entry("employer", "home_based_woman", "Tailoring / Darzan", "silai", area, None, text,
                  rate_info=None, working_hours=None, extra={"name": emp_name})
    elif sub_choice == "tutor":
        subject = random.choice(TUTOR_SUBJECTS)
        template = random.choice(EMP_HOME_WOMEN_TEMPLATES_TUTOR)
        text = template.format(area=area, subject=subject)
        add_entry("employer", "home_based_woman", "Home Tutor", subject, area, None, text,
                  rate_info=random_tutor_rate(), working_hours=random_tutor_hours(),
                  extra={"name": emp_name, "subjects": subject})
    else:
        template = random.choice(EMP_HOME_WOMEN_TEMPLATES_COOK)
        text = template.format(area=area)
        add_entry("employer", "home_based_woman", "Cook / Chef", "khana banane", area, None, text,
                  rate_info=random_cook_rate(), working_hours=None, extra={"name": emp_name})

# ---------------- EMPLOYERS: Bulk / general staffing (10) ----------------
for i in range(10):
    area = random.choice(AREAS)
    count = random.choice([1, 2, 3, 4, 5])
    template = random.choice(EMP_BULK_TEMPLATES)
    text = template.format(area=area, count=count)
    # infer role from template text roughly
    if "guard" in text.lower():
        role = "Security Guard"
        is_household = False
    elif "mazdoor" in text.lower():
        role = "Construction Labour"
        is_household = False
    elif "helper" in text.lower():
        role = "Domestic Helper"
        is_household = True
    elif "driver" in text.lower():
        role = "Driver"
        is_household = True
    else:
        role = "Loader / Helper"
        is_household = False
    emp_name = generate_employer_name(is_household=is_household)
    add_entry("employer", "bulk_staffing", role, None, area, None, text,
              rate_info=random_bulk_salary(), working_hours=random_bulk_hours(),
              extra={"name": emp_name, "count_needed": count})

# ---------------------------------------------------------
# Post-process: applicant_count and urgent flag
# Done as a separate pass (not inline in add_entry) so the randint
# calls don't shift the random sequence used for names/areas/rates
# above - keeps the seeded output reproducible if anyone tweaks the
# ranges here later without touching the generation loops.
# ---------------------------------------------------------
for e in entries:
    if e["type"] == "employer":
        e["applicant_count"] = random.randint(0, 8)
        e["urgent"] = random.random() < 0.15  # ~15% of listings flagged urgent
    else:
        e["applicant_count"] = random.randint(0, 5)  # "contacted N times" for workers

# ---------------------------------------------------------
# Save - 3 separate files inside data/
# ---------------------------------------------------------
random.shuffle(entries)
for idx, e in enumerate(entries, start=1):
    e["id"] = f"E{idx:03d}"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

workers = [e for e in entries if e["type"] == "worker"]
employers = [e for e in entries if e["type"] == "employer"]

with open(os.path.join(DATA_DIR, "seed_data.json"), "w", encoding="utf-8") as f:
    json.dump(entries, f, ensure_ascii=False, indent=2)

with open(os.path.join(DATA_DIR, "workers.json"), "w", encoding="utf-8") as f:
    json.dump(workers, f, ensure_ascii=False, indent=2)

with open(os.path.join(DATA_DIR, "employers.json"), "w", encoding="utf-8") as f:
    json.dump(employers, f, ensure_ascii=False, indent=2)

from collections import Counter
type_counts = Counter(e["type"] for e in entries)
cat_counts = Counter((e["type"], e["category"]) for e in entries)
area_counts = Counter(e["location"] for e in entries)

print(f"Total entries: {len(entries)}")
print(f"Workers: {type_counts['worker']}, Employers: {type_counts['employer']}")
print(f"Areas used ({len(AREAS)} total, from districts {TARGET_DISTRICTS}):")
for area, n in sorted(area_counts.items()):
    print(f"  {area:22s} : {n}")
print("\nBreakdown by category:")
for (t, c), n in sorted(cat_counts.items()):
    print(f"  {t:9s} | {c:18s} : {n}")

print("\nFiles written:")
print(f"  {os.path.join(DATA_DIR, 'seed_data.json')}")
print(f"  {os.path.join(DATA_DIR, 'workers.json')}")
print(f"  {os.path.join(DATA_DIR, 'employers.json')}")