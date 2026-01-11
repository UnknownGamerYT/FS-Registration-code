#!/usr/bin/env python3
"""
Categorize FS-Quiz questions into Mechanical / Electrical / Finance / Team Manager buckets.
Reads fsquiz_questions_with_answers.json, optionally uses FS-Rules_2026_v1.0.pdf to validate rule codes,
and writes per-category JSON files into categorized_questions/.
"""
import json
import re
import sys
import argparse
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Optional, Any

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # PDF parsing optional; we fall back to keyword-only categorization


SRC_JSON = Path("fsquiz_questions_with_answers.json")
RULES_PDF = Path("FS-Rules_2026_v1.0.pdf")
OUT_DIR = Path("categorized_questions")


def load_questions(path: Path) -> List[Dict]:
    if not path.exists():
        sys.exit(f"Missing {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "questions_full" in data:
        return data["questions_full"]
    sys.exit("Unrecognized JSON structure; expected list or key 'questions_full'.")


def load_valid_rule_codes() -> Set[str]:
    """Extract rule tokens from the PDF to reduce false positives."""
    if PdfReader is None or not RULES_PDF.exists():
        return set()
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(RULES_PDF)).pages)
    token_re = re.compile(r"\b((?:A|IN|T|CV|EV|S|D)\.?\s?\d+(?:\.\d+)*)")
    return {
        m.group(1)
        .replace(" ", "")
        .replace("\u202f", "")
        .replace("\u00a0", "")
        for m in token_re.finditer(text)
    }


def make_matcher(words: Iterable[str], phrases: Iterable[str] = ()) -> callable:
    regexes = [re.compile(r"\b" + re.escape(w) + r"\b") for w in words]
    phrases = list(phrases)

    def match(text: str) -> bool:
        if any(p in text for p in phrases):
            return True
        return any(r.search(text) for r in regexes)

    return match


COUNTRY_CODES = {
    "austria": "A",
    "croatia": "CRO",
    "germany": "DE",
    "netherlands": "NL",
    "hungary": "HU",
    "switzerland": "CH",
    "united kingdom": "UK",
    "great britain": "UK",
    "france": "FR",
    "spain": "ES",
    "italy": "IT",
    "portugal": "PT",
    "poland": "PL",
    "czech republic": "CZ",
    "usa": "US",
    "united states": "US",
    "canada": "CA",
    "india": "IN",
    "china": "CN",
    "japan": "JP",
}


def country_code(name: Any) -> str:
    if name is None:
        return ""
    n = str(name).strip()
    if not n:
        return ""
    key = n.lower()
    if key in COUNTRY_CODES:
        return COUNTRY_CODES[key]
    # fallback: first 3 letters uppercased
    return "".join(ch for ch in n[:3] if ch.isalnum()).upper()


def year_code(y: Any) -> str:
    if y is None:
        return ""
    s = str(y)
    if len(s) >= 2:
        return s[-2:]
    return s


# Keyword matchers
team_match = make_matcher(
    [
        "deadline",
        "document",
        "submission",
        "registration",
        "registered",
        "deregistered",
        "participant",
        "licence",
        "license",
        "briefing",
        "conduct",
        "pit",
        "eligibility",
        "protest",
        "captain",
        "team",
    ],
    phrases=["rules of conduct", "work area", "hot area", "practice area"],
)
el_match = make_matcher(
    [
        "accumulator",
        "battery",
        "cell",
        "cells",
        "inverter",
        "motor",
        "isolation",
        "insulation",
        "tsal",
        "imd",
        "ams",
        "hv",
        "tsvs",
        "lvs",
        "glv",
        "shutdown",
        "airs",
        "precharge",
        "bspd",
        "charger",
        "voltage",
        "current",
        "ohm",
        "amp",
        "pcb",
        "connector",
        "hvdc",
    ],
    phrases=["tractive system", "high voltage"],
)
finance_match = make_matcher(
    [
        "business",
        "cost",
        "bom",
        "static",
        "dynamic",
        "skidpad",
        "acceleration",
        "autocross",
        "endurance",
        "efficiency",
        "points",
        "scoring",
        "penalties",
        "penalty",
        "stint",
        "weather",
        "cone",
        "dnf",
        "manufacturing",
        "presentation",
    ],
    phrases=["design event", "design report", "business plan", "cost report", "driver change", "lap time", "lap times"],
)
mech_match = make_matcher(
    [
        "chassis",
        "monocoque",
        "aero",
        "wing",
        "suspension",
        "damper",
        "upright",
        "steering",
        "rack",
        "toe",
        "camber",
        "brake",
        "caliper",
        "rotor",
        "master",
        "seat",
        "harness",
        "restraint",
        "roll",
        "impact",
        "firewall",
        "wheel",
        "tire",
        "tyre",
        "fuel",
        "combustion",
        "exhaust",
        "throttle",
        "noise",
        "drivetrain",
        "gear",
        "gearbox",
        "differential",
        "chain",
        "belt",
        "powertrain",
        "tilt",
        "weigh",
        "fastener",
        "bolt",
        "stress",
        "strain",
        "modulus",
        "beam",
        "bending",
        "moment",
        "shear",
        "torque",
        "spring",
        "bearing",
        "weld",
        "buckling",
        "hoop",
        "frame",
        "tube",
    ]
)


def categorize(text: str, codes: List[str]) -> str:
    """Assign a category using rule codes first, then keyword heuristics."""
    t = text.lower()
    if codes:
        for c in codes:
            if c.startswith(("EV", "T11")):
                return "Electrical"
            if c.startswith(("CV", "T", "IN")):
                return "Mechanical"
            if c.startswith("A"):
                return "Team Manager"
            if c.startswith(("S", "D")):
                return "Finance"
    if team_match(t):
        return "Team Manager"
    if el_match(t):
        return "Electrical"
    if finance_match(t):
        return "Finance"
    if mech_match(t):
        return "Mechanical"
    return "Mechanical"  # default bucket for remaining technical items


def main() -> None:
    parser = argparse.ArgumentParser(description="Categorize questions into buckets.")
    parser.add_argument("--source", type=Path, default=SRC_JSON, help="Source questions JSON.")
    parser.add_argument("--country", nargs="*", help="Filter by country (exact string, can list multiple).")
    parser.add_argument("--year", nargs="*", help="Filter by year (int, multiple allowed).")
    args = parser.parse_args()

    questions = load_questions(args.source)
    valid_codes = load_valid_rule_codes()
    rule_pat = re.compile(r"\b((?:A|IN|T|CV|EV|S|D)\s?\d+(?:\.\d+)*)")

    countries_filter: Optional[Set[str]] = set(args.country) if args.country else None
    years_filter: Optional[Set[str]] = set(str(y) for y in args.year) if args.year else None

    buckets: Dict[str, List[Dict]] = defaultdict(list)
    country_year_buckets: Dict[str, Dict[str, Dict[str, List[Dict]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for q in questions:
        text = q.get("text", "") or ""
        codes = [c.replace(" ", "") for c in rule_pat.findall(text)]
        codes = [c for c in codes if c in valid_codes] if valid_codes else codes
        # metadata filters
        if countries_filter:
            qcountries = {str(c) for c in q.get("countries", [])}
            if not qcountries & countries_filter:
                continue
        if years_filter:
            qyears = {str(y) for y in q.get("years", [])}
            if not qyears & years_filter:
                continue

        cat = categorize(text, codes)
        buckets[cat].append(q)
        # populate country-year splits
        q_countries = q.get("countries") or []
        q_years = q.get("years") or []
        for c in q_countries:
            for y in q_years:
                country_year_buckets[c][str(y)][cat].append(q)

    OUT_DIR.mkdir(exist_ok=True)
    name_map = {
        "Mechanical": "questions_mechanical.json",
        "Electrical": "questions_electrical.json",
        "Finance": "questions_finance.json",
        "Team Manager": "questions_team_manager.json",
    }
    for cat, fname in name_map.items():
        out_path = OUT_DIR / fname
        out_path.write_text(json.dumps(buckets.get(cat, []), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{cat:12s}: {len(buckets.get(cat, [])):4d} -> {out_path}")

    # Write per-country, per-year splits
    def slugify(val: str) -> str:
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in str(val)).strip("_")

    for country, years_map in country_year_buckets.items():
        c_code = country_code(country) or slugify(country)
        for year, cat_map in years_map.items():
            y_code = year_code(year) or slugify(year)
            base_dir = OUT_DIR / "by_country_year" / slugify(c_code) / slugify(y_code)
            base_dir.mkdir(parents=True, exist_ok=True)
            for cat, qlist in cat_map.items():
                fname = name_map.get(cat, f"questions_{slugify(cat)}.json")
                out_path = base_dir / fname
                out_path.write_text(json.dumps(qlist, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Wrote country/year split: {country} ({c_code}) {year} ({y_code}) -> {base_dir}")

    print("Done.")


if __name__ == "__main__":
    main()
