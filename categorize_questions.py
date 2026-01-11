#!/usr/bin/env python3
"""
Categorize FS-Quiz questions into Mechanical / Electrical / Finance / Team Manager buckets.
Reads fsquiz_questions_with_answers.json, optionally uses FS-Rules_2026_v1.0.pdf to validate rule codes,
and writes per-category JSON files into categorized_questions/.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # PDF parsing optional; we fall back to keyword-only categorization


SRC_JSON = Path("fsquiz_questions_with_answers.json")
RULES_PDF = Path("FS-Rules_2026_v1.0.pdf")
OUT_DIR = Path("categorized_questions")


def load_questions() -> List[Dict]:
    if not SRC_JSON.exists():
        sys.exit(f"Missing {SRC_JSON}")
    data = json.loads(SRC_JSON.read_text(encoding="utf-8"))
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
    questions = load_questions()
    valid_codes = load_valid_rule_codes()
    rule_pat = re.compile(r"\b((?:A|IN|T|CV|EV|S|D)\s?\d+(?:\.\d+)*)")

    buckets: Dict[str, List[Dict]] = defaultdict(list)
    for q in questions:
        text = q.get("text", "") or ""
        codes = [c.replace(" ", "") for c in rule_pat.findall(text)]
        codes = [c for c in codes if c in valid_codes] if valid_codes else codes
        cat = categorize(text, codes)
        buckets[cat].append(q)

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

    print("Done.")


if __name__ == "__main__":
    main()
