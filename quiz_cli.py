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
    time_stats = compute_time_stats(questions)
    quiz = pick_questions(questions, count, min_options=1)

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
        print(f"Q{i:02d} [{qtype}]:\n{wrap(text)}")
        free_response = len(opts) <= 1

        # Images
        img_paths = q.get("question_images") or []
        opened_imgs: List[str] = []
        if img_paths:
            print("Images:")
            for p in img_paths:
                print(f"  - {p}")

            for p in img_paths:
                try:
                    img_path = Path(p)
                    if not img_path.is_absolute():
                        img_path = Path.cwd() / img_path
                    if platform.system() == "Windows":
                        subprocess.Popen(["start", "", str(img_path)], shell=True)
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", str(img_path)])
                    else:
                        subprocess.Popen(["xdg-open", str(img_path)])
                    opened_imgs.append(str(img_path))
                except Exception as e:
                    print(f"   (could not open image {p}: {e})")

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
                    return
                if low == "s":
                    print("Skipped.\n")
                    break
                if low == "i" and opened_imgs:
                    for p in opened_imgs:
                        try:
                            if platform.system() == "Windows":
                                subprocess.Popen(["start", "", str(p)], shell=True)
                            elif platform.system() == "Darwin":
                                subprocess.Popen(["open", str(p)])
                            else:
                                subprocess.Popen(["xdg-open", str(p)])
                        except Exception as e:
                            print(f"   (could not open image {p}: {e})")
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
                        # No correctness data; just echo expected if we have it
                        if expected:
                            print(f"ℹ️  Reference answer: {expected[0]}\n")
                        else:
                            print("ℹ️  No reference answer available.\n")
                else:
                    print("Recorded.\n")
                break
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
                return
            if low == "s":
                print("Skipped.\n")
                break
            if low == "i" and opened_imgs:
                for p in opened_imgs:
                    try:
                        if platform.system() == "Windows":
                            subprocess.Popen(["start", "", str(p)], shell=True)
                        elif platform.system() == "Darwin":
                            subprocess.Popen(["open", str(p)])
                        else:
                            subprocess.Popen(["xdg-open", str(p)])
                    except Exception as e:
                        print(f"   (could not open image {p}: {e})")
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
                    correct_labels = ",".join(letters[i] for i in correct)
                    print(f"{format_result(ok)} Correct answer(s): {correct_labels}\n")
                else:
                    print("ℹ️  No correct answer marked in dataset; response not scored.\n")
                break

        stop_event.set()
        if timer_thread:
            timer_thread.join(timeout=0.2)
        if args.timed:
            print()  # move to next line after countdown line

    if scored:
        print(f"Final score: {correct_count}/{scored} (scored questions). Presented: {asked}")
    elif asked:
        print(f"Presented {asked} questions, but none had a marked correct answer to score.")
    else:
        print("No questions were asked (insufficient data).")


if __name__ == "__main__":
    main()
