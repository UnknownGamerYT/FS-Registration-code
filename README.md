# FS Quiz Downloader, Categorizer, and CLI Quiz

This workspace contains tools to download the FS-Quiz dataset, categorize questions, and run a local CLI quiz.

## Files and scripts

- `download_fsquiz_everything.py`: Fetches the full FS-Quiz dataset (events, quizzes, questions, answers, solutions, images) from https://api.fs-quiz.eu/2 and writes `fsquiz_everything_full.json` plus downloads images into `images/`.
- `categorize_questions.py`: Splits questions into buckets (Mechanical, Electrical, Finance, Team Manager) based on rule IDs and keywords, writing JSON files under `categorized_questions/`.
- `quiz_cli.py`: Interactive quiz runner that reads questions, shows options or free-response, supports timers, auto-opens images, and tracks score.

Generated data files:
- `fsquiz_everything_full.json`: Full dataset with questions, answers, solutions, and image references.
- `fsquiz_questions_with_answers.json`: Questions + answers (used by the quiz).
- `categorized_questions/`:
  - `questions_mechanical.json`
  - `questions_electrical.json`
  - `questions_finance.json`
  - `questions_team_manager.json`

Images are stored in `images/`.

## Prerequisites

- Python 3. Install `pypdf` if not already available:
  ```bash
  python3 -m pip install --user pypdf --break-system-packages
  ```
  (The dataset download uses `requests`, already bundled in the scripts.)

## Usage

### 1) Download / refresh the dataset
```bash
python3 download_fsquiz_everything.py
```
This writes `fsquiz_everything_full.json` and downloads images to `images/`.

### 2) Enrich questions with country/year metadata
```bash
python3 enrich_questions_with_metadata.py
```
Adds `countries`, `years`, and `quiz_ids` to `fsquiz_questions_with_answers.json` by joining against `fsquiz_everything_full.json` (uses quiz/event info).

### 3) Categorize questions
```bash
python3 categorize_questions.py
# optionally filter
python3 categorize_questions.py --country Germany --year 2024
```
Creates/updates JSON files in `categorized_questions/` grouped by Mechanical, Electrical, Finance, and Team Manager, honoring optional country/year filters.

### 4) Run the CLI quiz
```bash
python3 quiz_cli.py
```
If you omit flags, the quiz will prompt for:
- Category (choose mechanical/electrical/finance/team-manager or leave empty for all)
- Country filter (comma-separated, or blank for all)
- Year filter (comma-separated, or blank for all)
- Question count (default 20)
- Timer on/off (default off)

Features:
- Multiple-choice questions (select letters), free-response for single-answer questions.
- Timer mode (counts down using question time or median time if missing).
- Auto-opens question images and lets you reopen them with input `i`.
- Accepts numeric ranges when provided in answers (e.g., `8.9-9.3`).
- Shows country/year metadata (if present) and can filter by it.

Optional flags to skip prompts:
```bash
python3 quiz_cli.py --category mechanical --count 10 --timed --country Germany --year 2024 2025
```

## Notes
- Image opening uses the system viewer (`start` on Windows, `open` on macOS, `xdg-open` on Linux). If you prefer not to auto-open, we can add a toggle.
- Free-response grading is tolerant to whitespace/case and compares numeric answers (including ranges).
- The timer is informational; answers are still accepted if time runs out.
