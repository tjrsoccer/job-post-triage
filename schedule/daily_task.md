# Daily run: design and draft scheduled task

**Status: draft. No schedule has been created yet.** Pick a delivery
option below first.

## Why a scheduled Claude task, not a cron script

Indeed has no public API that a Python script can call, so the Indeed pull
goes through the Indeed connector, which only a Claude session can use.
Greenhouse and Lever are plain Python (`fetch_jobs.py`, from PR #3). So one scheduled Claude task does the whole day:

1. Pull Indeed through the connector, save each result, and run
   `python fetch_jobs.py indeed-import FILE` (names and de-duplicates it
   into `inbox/`).
2. Run `python fetch_jobs.py` for Greenhouse and Lever boards.
3. Run `python daily.py`. It screens only postings it has not seen, using
   the same layer1 + Claude prompt as `triage.py`, and writes
   `reports/YYYY-MM-DD.csv` and `.html` with only the Apply results.
4. Deliver (option A or B below).

## Delivery options

| | A. Email | B. Google Sheet |
|---|---|---|
| What you get | One email a day, best fit first, CSV attached. Nothing on a day with no Apply results. | One row per Apply result appended to a sheet. Add a "Status" column to track what you applied to. |
| Sent by | The Gmail connector in the scheduled task (no passwords stored). `daily.py --email` also works over Gmail SMTP with an app password, if you ever run it outside Claude. | The Google Sheets connector in the scheduled task. |
| Good for | Noticing new jobs fast | Tracking applications over time (fits the README's "track how my Apply decisions turn out") |

My recommendation is **B, the Sheet**, with a one-line email or mobile
notification only when there are new rows, because the sheet doubles as
the application tracker. Both can run together.

## Open questions and guesses

- **GUESS: time.** 7:00 AM Pacific, every day.
- **GUESS: what gets sent.** Every APPLY, including long shots (capped at
  fit 50). Change `should_send()` in `daily.py` to filter more.
- **GUESS: quiet days.** No email when there are no Apply results and no
  errors.
- **Memory between runs.** A cloud scheduled task starts from a fresh copy
  of the repo each day, so `state/seen.txt` (and job-pulling's `seen.json`)
  would be forgotten. Options: (1) the task commits those two files back to
  the repo after each run (ids only, no posting text); (2) run the task on
  your computer, where files persist; (3) with option B, read the ids
  already in the sheet. Default in the draft below: (1).
- **API key.** `daily.py` calls the Claude API through `triage.py`, so the
  scheduled task's environment needs `ANTHROPIC_API_KEY` set as a secret.
  Cost is about a penny per posting that survives layer one.
- **Search terms for Indeed.** Defined by the job-pulling PR, not here.

## Draft task prompt

```
Daily job triage run for tjrsoccer/job-post-triage.

1. Search Indeed with the connector using "indeed_searches" and
   "indeed_country" from fetch_config.json. Save each get_job_details
   result as-is to a .md file and run:
   python fetch_jobs.py indeed-import <files>
2. Run: python fetch_jobs.py
3. Run: python daily.py
4. If reports/<today>.csv has any rows:
   [A] Email them with the Gmail connector to Tyler, subject
       "Job triage <date>: N to apply to", body = reports/<today>.html.
   [B] Append each row to the "Apply" tab of <SHEET LINK> with the
       Google Sheets connector, columns in the CSV's order plus a blank
       Status column.
   If daily.py listed postings it could not screen, mention them.
5. Commit state/seen.txt and seen.json and push, so tomorrow's run
   skips them. Do not commit inbox/ or reports/ (full posting text).
6. If any step fails, stop and report what failed. Never send a
   partial email that looks complete.
```
