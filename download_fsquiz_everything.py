#!/usr/bin/env python3
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, DefaultDict
from collections import defaultdict

import requests

API_BASE = "https://api.fs-quiz.eu/2"
IMG_HOST = "https://img.fs-quiz.eu"

OUT_JSON_FULL = Path("fsquiz_everything_full.json")
OUT_JSON_QA   = Path("fsquiz_questions_with_answers.json")
IMG_DIR = Path("images")

SLEEP_S = 0.25
TIMEOUT_S = 30
START_ID_STEP = 25
MAX_START_ID = 2_000_000

session = requests.Session()
session.headers.update({"Accept": "*/*"})


def sleep():
    time.sleep(SLEEP_S)


def safe_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{API_BASE}{path}"
    r = session.get(url, params=params, timeout=TIMEOUT_S)
    r.raise_for_status()
    sleep()
    return r.json()


def try_get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    try:
        return get_json(path, params=params)
    except Exception:
        return None


def list_with_fallback_paging(path: str, list_key: str) -> List[Dict[str, Any]]:
    """
    Robust list fetch:
    - try without start_id
    - if looks capped (often 25), page using start_id=1, 26, 51...
    """
    first = try_get_json(path)
    if first and isinstance(first.get(list_key), list):
        items = first[list_key]
        if len(items) != 25:
            return items
    else:
        items = []

    results: List[Dict[str, Any]] = []
    start_id = 1
    failures = 0

    while True:
        page = try_get_json(path, params={"start_id": start_id})
        if page is None:
            failures += 1
            if failures >= 3:
                break
            time.sleep(1.0 * failures)
            start_id += START_ID_STEP
            continue

        failures = 0
        page_items = page.get(list_key, [])
        if not page_items:
            break

        results.extend(page_items)

        if len(results) % 250 == 0:
            print(f"  ...{path} collected {len(results)} items so far")

        start_id += START_ID_STEP
        if start_id > MAX_START_ID:
            break

    return results if results else items


# ---------------- Images ----------------
def download_image_bytes(url: str) -> bytes:
    r = session.get(url, timeout=TIMEOUT_S)
    r.raise_for_status()
    sleep()
    return r.content


def download_image_for_question(question_id: int, img: Dict[str, Any]) -> Optional[str]:
    """
    img: { "img_id": 1, "path": "12_1.jpg" }
    """
    path = img.get("path")
    if not path:
        return None

    img_id = safe_int(img.get("img_id")) or 0
    fname_only = Path(path).name
    out = IMG_DIR / f"q{question_id:06d}__img{img_id:06d}__{fname_only}"

    if out.exists():
        return str(out)

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = download_image_bytes(f"{IMG_HOST}/{path}")
    out.write_bytes(data)
    return str(out)


def download_image_for_solution(solution_id: int, img: Dict[str, Any]) -> Optional[str]:
    path = img.get("path")
    if not path:
        return None

    img_id = safe_int(img.get("img_id")) or 0
    fname_only = Path(path).name
    out = IMG_DIR / f"s{solution_id:06d}__img{img_id:06d}__{fname_only}"

    if out.exists():
        return str(out)

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    data = download_image_bytes(f"{IMG_HOST}/{path}")
    out.write_bytes(data)
    return str(out)


# ---------------- Helpers: extract answer options ----------------
def extract_answer_options(qfull: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    The schema differs between quizzes. We try common fields:
      - answers: [{answer_id/id, text, ...}]
      - options: [...]
      - possible_answers / possibleAnswers
    """
    for key in ("answers", "options", "possible_answers", "possibleAnswers"):
        val = qfull.get(key)
        if isinstance(val, list):
            return val
    return []


def main():
    print("Downloading FS-Quiz dataset (full) + images + solutions + merged Q&A…")

    # 1) events
    print("1) /event/all")
    events = get_json("/event/all").get("events", [])
    print(f"   events: {len(events)}")

    # 2) quizzes
    print("2) /quiz")
    quizzes = list_with_fallback_paging("/quiz", "quizzes")
    print(f"   quizzes: {len(quizzes)}")

    # 3) quiz info
    print("3) /quiz/{id}/info")
    quizzes_info: List[Dict[str, Any]] = []
    for i, q in enumerate(quizzes, start=1):
        qid = q.get("quiz_id")
        if qid is None:
            continue
        qi = try_get_json(f"/quiz/{qid}/info")
        if qi is not None:
            quizzes_info.append(qi)
        if i % 100 == 0:
            print(f"   ...quiz infos {i}/{len(quizzes)}")
    print(f"   quiz infos: {len(quizzes_info)}")

    # 4) question ids
    print("4) /question (collect ids)")
    q_short = list_with_fallback_paging("/question", "questions")
    qids = [safe_int(q.get("question_id")) for q in q_short]
    qids = [qid for qid in qids if qid is not None]
    print(f"   question ids: {len(qids)}")

    # 5) full questions + question images
    print("5) /question/{id} + /question/{id}/images + answers")
    questions_full: List[Dict[str, Any]] = []
    question_images: Dict[str, List[str]] = {}
    question_answers: Dict[str, List[Dict[str, Any]]] = {}

    for i, qid in enumerate(qids, start=1):
        qfull = try_get_json(f"/question/{qid}") or {"question_id": qid, "error": "failed_to_fetch_full_question"}
        questions_full.append(qfull)

        saved_imgs: List[str] = []
        imgs = try_get_json(f"/question/{qid}/images")
        if imgs and isinstance(imgs.get("images"), list):
            for img in imgs["images"]:
                try:
                    local = download_image_for_question(qid, img)
                    if local:
                        saved_imgs.append(local)
                except Exception:
                    pass
        question_images[str(qid)] = saved_imgs

        # Try to fetch answers via per-question endpoint
        ans_list: List[Dict[str, Any]] = []
        answers = try_get_json(f"/question/{qid}/answers")
        if answers and isinstance(answers.get("answers"), list):
            ans_list = answers["answers"]
        question_answers[str(qid)] = ans_list

        if i % 50 == 0:
            print(f"   ...questions {i}/{len(qids)} | answers fetched: {i}")

    print(f"   full questions: {len(questions_full)}")
    print(f"   questions with answers via /question/{{id}}/answers: {sum(1 for v in question_answers.values() if v)}")

    # 5b) Backfill answers for missing questions via bulk /answer
    missing_answers = [qid for qid, ans in question_answers.items() if not ans]
    if missing_answers:
        print("5b) /answer (bulk) to backfill missing answers")
        bulk_answers = list_with_fallback_paging("/answer", "answers")
        by_qid: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
        for ans in bulk_answers:
            qid = safe_int(ans.get("question_id"))
            if qid is None:
                continue
            by_qid[str(qid)].append(ans)

        filled = 0
        for qid in missing_answers:
            if by_qid.get(qid):
                question_answers[qid] = by_qid[qid]
                filled += 1
        print(f"   backfilled answers for {filled}/{len(missing_answers)} missing questions")

    # 6) solutions: pull ALL solutions (not only referenced ones)
    # FS-Quiz exposes a Solution API (separate dataset). :contentReference[oaicite:1]{index=1}
    print("6) /solution (collect all)")
    solutions_short = list_with_fallback_paging("/solution", "solutions")
    sids = [safe_int(s.get("solution_id")) for s in solutions_short]
    sids = [sid for sid in sids if sid is not None]
    print(f"   solution ids: {len(sids)}")

    # 7) solution details + solution images
    print("7) /solution/{id} + /solution/{id}/images")
    solutions: Dict[str, Any] = {}
    solution_images: Dict[str, List[str]] = {}

    for i, sid in enumerate(sids, start=1):
        sfull = try_get_json(f"/solution/{sid}") or {"solution_id": sid, "error": "failed_to_fetch_solution"}
        solutions[str(sid)] = sfull

        saved_imgs: List[str] = []
        imgs = try_get_json(f"/solution/{sid}/images")
        if imgs and isinstance(imgs.get("images"), list):
            for img in imgs["images"]:
                try:
                    local = download_image_for_solution(sid, img)
                    if local:
                        saved_imgs.append(local)
                except Exception:
                    pass
        solution_images[str(sid)] = saved_imgs

        if i % 200 == 0:
            print(f"   ...solutions {i}/{len(sids)}")

    print(f"   solutions stored: {len(solutions)}")

    # 8) Build mapping: question_id -> solutions
    # Most solution objects include question_id (or similar). If not, we keep them unlinked.
    sol_by_qid: DefaultDict[int, List[Dict[str, Any]]] = defaultdict(list)
    unlinked = 0

    for sid_str, s in solutions.items():
        qid = safe_int(s.get("question_id") or s.get("questionId"))
        if qid is None:
            unlinked += 1
            continue
        sol_by_qid[qid].append(s)

    print(f"   solutions linked to questions: {len(sol_by_qid)} question_ids (unlinked solutions: {unlinked})")

    # 9) Produce merged Q&A file
    merged: List[Dict[str, Any]] = []
    for q in questions_full:
        qid = safe_int(q.get("question_id")) or 0
        merged.append({
            "question_id": qid,
            "text": q.get("text"),
            "type": q.get("type"),
            "time": q.get("time"),
            "answer_options": extract_answer_options(q),          # possible answers (if provided)
            "solutions": sol_by_qid.get(qid, []),                # contains correct answers if public
            "question_images": question_images.get(str(qid), []),
            "answers": question_answers.get(str(qid), []),       # answers fetched via API
        })

    # 10) Write outputs
    everything = {
        "downloaded_at_unix": int(time.time()),
        "api_base": API_BASE,
        "img_host": IMG_HOST,
        "events": events,
        "quizzes_short": quizzes,
        "quizzes_info": quizzes_info,
        "questions_full": questions_full,
        "question_answers": question_answers,
        "solutions": solutions,
        "question_images": question_images,
        "solution_images": solution_images,
    }

    OUT_JSON_FULL.write_text(json.dumps(everything, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_JSON_QA.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ Written: {OUT_JSON_FULL.resolve()}")
    print(f"✅ Written merged Q&A: {OUT_JSON_QA.resolve()}")
    print(f"✅ Images folder: {IMG_DIR.resolve()}")
    print("Done.")


if __name__ == "__main__":
    main()
