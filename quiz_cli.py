#!/usr/bin/env python3
"""
Friendly CLI quiz for FS-Quiz datasets.

Usage examples:
  python3 quiz_cli.py                   # use fsquiz_questions_with_answers.json
  python3 quiz_cli.py --category mechanical --count 25
  python3 quiz_cli.py --source categorized_questions/questions_electrical.json
"""
import argparse
import json
import random
import re
import string
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from statistics import median
import platform
import subprocess
import json
try:
    from PIL import Image, ImageTk
    import tkinter as tk
    INTERNAL_VIEWER_AVAILABLE = True
except Exception:
    INTERNAL_VIEWER_AVAILABLE = False
    Image = ImageTk = tk = None


DEFAULT_SOURCE = Path("fsquiz_questions_with_answers.json")
CATEGORY_FILES = {
    "mechanical": Path("categorized_questions/questions_mechanical.json"),
    "electrical": Path("categorized_questions/questions_electrical.json"),
    "finance": Path("categorized_questions/questions_finance.json"),
    "team-manager": Path("categorized_questions/questions_team_manager.json"),
}


def wrap(text: str, width: int = 88) -> str:
    """
    Wrap text while respecting explicit newlines (including literal '\\n' sequences).
    """
    if not text:
        return ""
    normalized = text.replace("\\n", "\n")
    lines = []
    for para in normalized.splitlines():
        if para.strip() == "":
            lines.append("")  # preserve blank line
            continue
        lines.extend(textwrap.wrap(para, width=width))
    return "\n".join(lines)


def load_questions(path: Path) -> List[Dict]:
    if not path.exists():
        sys.exit(f"Source file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "questions_full" in data:
        return data["questions_full"]
    sys.exit(f"Unrecognized JSON structure in {path}")


def load_full_meta(full_path: Path = Path("fsquiz_everything_full.json")) -> Dict[int, Dict[str, List]]:
    """Load question -> meta (countries, years, quiz_ids) from the full dataset."""
    if not full_path.exists():
        return {}
    full = json.loads(full_path.read_text(encoding="utf-8"))
    events = {e.get("id"): e for e in full.get("events", [])}
    quizzes = {q.get("quiz_id"): q for q in full.get("quizzes_short", [])}

    qmeta: Dict[int, Dict[str, List]] = {}
    for q in full.get("questions_full", []):
        qid = q.get("question_id")
        if qid is None:
            continue
        entry = {"countries": [], "years": [], "quiz_ids": []}
        for qref in q.get("quizzes", []) or []:
            qzid = qref.get("quiz_id")
            if qzid is None:
                continue
            entry["quiz_ids"].append(int(qzid))
            qz = quizzes.get(qzid, {})
            yr = qz.get("year")
            if yr is not None:
                entry["years"].append(yr)
            ev = events.get(qz.get("event_id"))
            if ev:
                ct = ev.get("country")
                if ct is not None:
                    entry["countries"].append(ct)
        qmeta[int(qid)] = entry
    return qmeta


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
    "turkey": "TUR",
    "turkiye": "TUR",
    "türkiye": "TUR",
}


def country_code(name: str) -> str:
    key = (
        name.lower()
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ä", "a")
        .replace("ß", "ss")
    )
    if key in COUNTRY_CODES:
        return COUNTRY_CODES[key]
    return "".join(ch for ch in name[:3] if ch.isalnum()).upper()


def year_code(y: any) -> str:
    s = str(y)
    return s[-2:] if len(s) >= 2 else s


def open_images(img_paths: List[str]):
    internal_windows: List = []
    internal_photos: List = []
    external_procs: List = []
    for p in img_paths:
        try:
            img_path = Path(p)
            if not img_path.is_absolute():
                img_path = Path.cwd() / img_path
            if INTERNAL_VIEWER_AVAILABLE:
                img = Image.open(img_path)
                win = tk.Tk()
                win.title(str(img_path))
                photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(win, image=photo)
                lbl.image = photo
                lbl.pack()
                win.update_idletasks()
                win.update()
                internal_windows.append(win)
                internal_photos.append(photo)
            else:
                if platform.system() == "Windows":
                    proc = subprocess.Popen(["start", "", str(img_path)], shell=True)
                elif platform.system() == "Darwin":
                    proc = subprocess.Popen(["open", str(img_path)])
                else:
                    proc = subprocess.Popen(["xdg-open", str(img_path)])
                external_procs.append(proc)
        except Exception as e:
            print(f"   (could not open image {p}: {e})")
    return internal_windows, internal_photos, external_procs


def close_images(internal_windows: List, external_procs: List):
    for w in internal_windows:
        try:
            w.destroy()
        except Exception:
            pass
    for proc in external_procs:
        try:
            proc.terminate()
        except Exception:
            pass


def confirm_list(kind: str, selections: List[str], available_hint: str = "") -> List[str]:
    while True:
        if selections:
            print(f"Selected {kind}: {', '.join(selections)}")
            resp = input(f"Continue with these {kind}? [y=continue / n=edit]: ").strip().lower()
            if resp.startswith("y"):
                return selections
        if available_hint:
            print(available_hint)
        new_in = input(f"Enter {kind} (comma-separated, blank for all): ").strip()
        if not new_in:
            return []
        selections = [s.strip() for s in new_in.split(",") if s.strip()]


def extract_options(q: Dict) -> Tuple[List[str], List[int]]:
    """
    Return (options_text, correct_indexes).
    Only consider answer options with non-empty text.
    """
    answers = q.get("answers") or []
    opts: List[str] = []
    correct: List[int] = []
    for ans in answers:
        txt = (ans.get("answer_text") or ans.get("text") or "").strip()
        if not txt:
            continue
        idx = len(opts)
        opts.append(txt)
        if ans.get("is_correct") is True or ans.get("correct") is True:
            correct.append(idx)
    return opts, correct


def pick_questions(questions: Sequence[Dict], count: int, min_options: int = 1) -> List[Dict]:
    # Filter to questions that have at least `min_options` answer options.
    pool: List[Dict] = []
    for q in questions:
        opts, correct = extract_options(q)
        if len(opts) >= min_options:
            pool.append(q)
    if not pool:
        sys.exit("No questions with answers available.")
    random.shuffle(pool)
    return pool[: min(count, len(pool))]


def format_result(ok: bool) -> str:
    return "✅" if ok else "❌"


def parse_numeric_range(text: str):
    """
    Try to parse a numeric range like '8.9-9.3' or '8.9 – 9.3' or '8.9 to 9.3'.
    Returns (lo, hi) or None.
    """
    if not text:
        return None
    cleaned = text.replace(",", ".")
    m = re.match(r"\\s*([-+]?[0-9]*\\.?[0-9]+)\\s*(?:-|–|to)\\s*([-+]?[0-9]*\\.?[0-9]+)\\s*$", cleaned, re.IGNORECASE)
    if not m:
        return None
    try:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi
    except Exception:
        return None


def compute_time_stats(questions: Sequence[Dict]) -> Dict[str, float]:
    """Compute median times per type and overall (using only positive values)."""
    by_type: Dict[str, List[float]] = {}
    all_times: List[float] = []
    for q in questions:
        tval = q.get("time")
        if isinstance(tval, (int, float)) and tval > 0:
            all_times.append(float(tval))
            qtype = q.get("type") or "unknown"
            by_type.setdefault(qtype, []).append(float(tval))
    stats: Dict[str, float] = {}
    for qt, vals in by_type.items():
        stats[qt] = median(vals)
    stats["__all__"] = median(all_times) if all_times else 60.0
    return stats


def time_limit_for_question(q: Dict, stats: Dict[str, float]) -> int:
    tval = q.get("time")
    if isinstance(tval, (int, float)) and tval > 0:
        return int(tval)
    qtype = q.get("type") or "unknown"
    fallback = stats.get(qtype) or stats.get("__all__", 60.0)
    # Clamp to a reasonable range
    return int(max(30, min(fallback, 900)))


def run_countdown(limit_s: int, stop_event: threading.Event, timed_out_flag: List[bool]) -> None:
    for remaining in range(limit_s, 0, -1):
        if stop_event.is_set():
            return
        print(f"\r⏳ {remaining:3d}s remaining", end="", flush=True)
        time.sleep(1)
    if not stop_event.is_set():
        timed_out_flag[0] = True
        print("\r⏰ Time is up! Press enter to answer (not enforced).   ", end="", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a quick FS quiz from local JSON.")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Path to questions JSON (default: fsquiz_questions_with_answers.json)",
    )
    parser.add_argument(
        "--category",
        choices=sorted(CATEGORY_FILES.keys()),
        help="Pick a predefined category file instead of --source.",
    )
    parser.add_argument("--count", type=int, help="Number of questions to ask (default: prompt)")
    parser.add_argument("--country", nargs="*", help="Filter by country (one or more).")
    parser.add_argument("--year", nargs="*", help="Filter by year (one or more, e.g., 2024 2025).")
    parser.add_argument(
        "--timed",
        action="store_true",
        help="Show a countdown timer. For missing times, use median time of similar questions.",
    )
    args = parser.parse_args()

    # Interactive prompts if flags not provided
    category = args.category
    if category is None:
        cat_in = input(f"Pick category [{'/'.join(sorted(CATEGORY_FILES.keys()))} or leave empty for all]: ").strip().lower()
        category = cat_in or None

    count = args.count
    if count is None:
        try:
            count = int(input("How many questions? [default 20]: ").strip() or "20")
        except Exception:
            count = 20

    timed = args.timed
    if not args.timed:
        t_in = input("Enable timer? [y/n, default n]: ").strip().lower()
        timed = t_in.startswith("y")

    src_path = CATEGORY_FILES.get(category) if category else args.source
    questions = load_questions(src_path)

    # If no country/year metadata present, attempt in-memory enrichment from full dataset.
    if not any(q.get("countries") or q.get("years") for q in questions):
        meta = load_full_meta()
        if meta:
            enriched = []
            for q in questions:
                qid = q.get("question_id")
                m = meta.get(int(qid)) if qid is not None else None
                if m:
                    q = dict(q)
                    q["countries"] = m.get("countries", [])
                    q["years"] = m.get("years", [])
                    q["quiz_ids"] = m.get("quiz_ids", [])
                enriched.append(q)
            questions = enriched
        else:
            print("⚠️  No country/year metadata found. Run enrich_questions_with_metadata.py for best results.")

    # Build available metadata options
    def uniq(vals):
        return sorted({v for v in vals if v is not None})

    all_countries = uniq([c for q in questions for c in q.get("countries", [])])
    country_display = [f"{country_code(c).lower()} ({c})" for c in all_countries]

    countries = args.country
    if countries is None:
        available_hint = f"Available countries: {', '.join(country_display)}" if country_display else "Available countries: (none detected)"
        norm_map = {country_code(c).lower(): c for c in all_countries}
        norm_full = {c.lower(): c for c in all_countries}
        selections: List[str] = []
        while True:
            if selections:
                print(f"Selected countries: {', '.join(selections)}")
                resp = input("Continue? [y=continue / n=reset / a=add]: ").strip().lower()
                if resp.startswith("y"):
                    break
                if resp.startswith("n"):
                    selections = []
            hint = available_hint
            if selections and all_countries:
                remaining = [c for c in all_countries if c not in selections]
                if remaining:
                    hint = f"Available (remaining) countries: {', '.join(f'{country_code(c).lower()} ({c})' for c in remaining)}"
            print(hint)
            c_in = input("Enter countries (comma-separated, blank for all): ").strip()
            if not c_in:
                if selections:
                    # keep existing if user just presses enter after add/reset prompt
                    continue
                selections = []
                break
            tokens = [t.strip() for t in c_in.split(",") if t.strip()]
            chosen = []
            for t in tokens:
                tl = t.lower()
                if tl in norm_map:
                    chosen.append(norm_map[tl])
                elif tl in norm_full:
                    chosen.append(norm_full[tl])
                else:
                    chosen.append(t)  # fallback
            # merge and de-dup
            selections = list(dict.fromkeys(selections + chosen))
        countries = selections

    # Restrict available years based on country selection, if any
    def country_match(q):
        if not countries:
            return True
        qcs = {str(c).lower() for c in q.get("countries", [])}
        return bool(qcs & {c.lower() for c in countries})

    available_years = uniq([y for q in questions if country_match(q) for y in q.get("years", [])])
    year_display = [f"{year_code(y)} ({y})" for y in available_years]

    years = args.year
    if years is None:
        norm_map_year = {year_code(y): str(y) for y in available_years}
        norm_full_year = {str(y): str(y) for y in available_years}
        selections: List[str] = []
        while True:
            if selections:
                print(f"Selected years: {', '.join(selections)}")
                resp = input("Continue? [y=continue / n=reset / a=add]: ").strip().lower()
                if resp.startswith("y"):
                    break
                if resp.startswith("n"):
                    selections = []
            if year_display:
                print(f"Available years: {', '.join(year_display)}")
            else:
                print("Available years: (none detected)")
            y_in = input("Enter years (comma-separated, blank for all): ").strip()
            if not y_in:
                if selections:
                    continue
                selections = []
                break
            tokens = [t.strip() for t in y_in.split(",") if t.strip()]
            chosen = []
            for t in tokens:
                if t in norm_map_year:
                    chosen.append(norm_map_year[t])
                elif t in norm_full_year:
                    chosen.append(norm_full_year[t])
                else:
                    chosen.append(t)
            selections = list(dict.fromkeys(selections + chosen))
        years = selections

    time_stats = compute_time_stats(questions)
    # apply metadata filters
    def match_meta(q):
        if countries:
            qcs = {str(c).lower() for c in q.get("countries", [])}
            if not qcs & {c.lower() for c in countries}:
                return False
        if years:
            qys = {str(y) for y in q.get("years", [])}
            if not qys & set(years):
                return False
        return True

    filtered = [q for q in questions if match_meta(q)]
    quiz = pick_questions(filtered if filtered else questions, count, min_options=1)

    print(f"\nFS Quiz — {len(quiz)} questions (source: {src_path})")
    print("Answer with letter(s), e.g., 'a' or 'a,c'. Type 'q' to quit, 's' to skip.\n")

    asked = correct_count = scored = 0
    for i, q in enumerate(quiz, start=1):
        text = (q.get("text") or "").strip()
        qtype = q.get("type") or "unknown"
        opts, correct = extract_options(q)

        # Present as long as there is at least one option
        asked += 1

        letters = list(string.ascii_lowercase)
        meta_bits = []
        if q.get("countries"):
            meta_bits.append("countries: " + ", ".join(map(str, q.get("countries", []))))
        if q.get("years"):
            meta_bits.append("years: " + ", ".join(map(str, q.get("years", []))))
        if q.get("quiz_ids"):
            meta_bits.append("quizzes: " + ", ".join(map(str, q.get("quiz_ids", []))))
        meta_line = f" ({'; '.join(meta_bits)})" if meta_bits else ""

        print(f"Q{i:02d} [{qtype}]{meta_line}:\n{wrap(text)}")
        free_response = (qtype and str(qtype).lower() == "input") or len(opts) <= 1

        # Images
        img_paths = q.get("question_images") or []
        opened_imgs: List[str] = []
        internal_windows: List = []
        internal_photos: List = []
        external_procs: List = []
        if img_paths:
            print("Images:")
            for p in img_paths:
                print(f"  - {p}")

            internal_windows, internal_photos, external_procs = open_images(img_paths)
            opened_imgs = [str(Path(p)) for p in img_paths]

        stop_event = threading.Event()
        timed_out = [False]
        timer_thread = None

        if args.timed:
            limit = time_limit_for_question(q, time_stats)
            print(f"(Time allowed: {limit}s)")
            timer_thread = threading.Thread(target=run_countdown, args=(limit, stop_event, timed_out), daemon=True)
            timer_thread.start()

        if free_response:
            if opts:
                print("(Free response; enter your answer)")
            # Loop until valid control input
            finished = False
            while True:
                prompt = "Your answer (q=quit, s=skip"
                if opened_imgs:
                    prompt += ", i=reopen image"
                prompt += "): "
                user_in = input(prompt).strip()
                low = user_in.lower()
                if low == "q":
                    stop_event.set()
                    if timer_thread:
                        timer_thread.join(timeout=0.2)
                    close_images(internal_windows, external_procs)
                    return
                if low == "s":
                    print("Skipped.\n")
                    break
                if low == "i" and opened_imgs:
                    iw, ip, ep = open_images(opened_imgs)
                    internal_windows.extend(iw)
                    internal_photos.extend(ip)
                    external_procs.extend(ep)
                    continue
                if user_in == "":
                    print("Please enter an answer or 's' to skip.")
                    continue

                # Evaluate if we have marked correct answers
                if correct or opts:
                    expected = [opts[i] for i in correct] if correct else opts

                    def norm(s: str) -> str:
                        return " ".join(s.strip().lower().split())

                    def to_float(s: str):
                        try:
                            return float(s.replace(",", "."))
                        except Exception:
                            return None
                    def range_of(s: str):
                        return parse_numeric_range(s)

                    user_norm = norm(user_in)
                    ok = False
                    user_range = range_of(user_in)
                    user_float = to_float(user_in)
                    for exp in expected:
                        exp_norm = norm(exp)
                        if user_norm == exp_norm:
                            ok = True
                            break
                        e_range = range_of(exp)
                        e_float = to_float(exp)
                        # numeric equality
                        if user_float is not None and e_float is not None and abs(user_float - e_float) < 1e-3:
                            ok = True
                            break
                        # numeric inside expected range
                        if e_range and user_float is not None and e_range[0] - 1e-6 <= user_float <= e_range[1] + 1e-6:
                            ok = True
                            break
                        # numeric range in user input vs expected float
                        if user_range and e_float is not None and user_range[0] - 1e-6 <= e_float <= user_range[1] + 1e-6:
                            ok = True
                            break
                    if correct:
                        scored += 1
                        if ok:
                            correct_count += 1
                            print(f"{format_result(ok)} Correct answer: {expected[0] if expected else '(not provided)'}\n")
                        else:
                            correct_text = "; ".join(expected) if expected else "(not provided)"
                            print(f"{format_result(ok)} Correct answer: {correct_text}\n")
                    else:
                        # No correctness data; just echo expected if we have it
                        if expected:
                            print(f"ℹ️  Reference answer: {expected[0]}\n")
                        else:
                            print("ℹ️  No reference answer available.\n")
                else:
                    print("Recorded.\n")
                finished = True
                break
            # finalize this question
            stop_event.set()
            if timer_thread:
                timer_thread.join(timeout=0.2)
            if args.timed:
                print()
            close_images(internal_windows, external_procs)
            if finished:
                continue
        else:
            for idx, opt in enumerate(opts):
                print(f"  {letters[idx]}) {wrap(opt)}")

        # Loop until a valid response is given for this question
        while True:
            prompt = "Your answer (q=quit, s=skip"
            if opened_imgs:
                prompt += ", i=reopen image"
            prompt += "): "
            user_raw = input(prompt).strip()
            low = user_raw.lower()
            if low == "q":
                stop_event.set()
                if timer_thread:
                    timer_thread.join(timeout=0.2)
                close_images(internal_windows, external_procs)
                return
            if low == "s":
                print("Skipped.\n")
                break
            if low == "i" and opened_imgs:
                iw, ip, ep = open_images(opened_imgs)
                internal_windows.extend(iw)
                internal_photos.extend(ip)
                external_procs.extend(ep)
                continue

            picks = {
                letters.index(ch)
                for ch in low.replace(" ", "").split(",")
                if ch in letters[: len(opts)]
            }
            if not picks:
                print("Invalid input, try again.")
                continue

            if correct:
                scored += 1
                ok = picks == set(correct)
                correct_count += 1 if ok else 0
                correct_text = "; ".join(opts[i] for i in correct if i < len(opts))
                print(f"{format_result(ok)} Correct: {correct_text}")
                print()
            else:
                print("ℹ️  No correct answer marked in dataset; response not scored.\n")
            break

        stop_event.set()
        if timer_thread:
            timer_thread.join(timeout=0.2)
        if args.timed:
            print()  # move to next line after countdown line
        close_images(internal_windows, external_procs)

    if scored:
        print(f"Final score: {correct_count}/{scored} (scored questions). Presented: {asked}")
    elif asked:
        print(f"Presented {asked} questions, but none had a marked correct answer to score.")
    else:
        print("No questions were asked (insufficient data).")


if __name__ == "__main__":
    main()
