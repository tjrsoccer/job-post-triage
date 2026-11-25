"""
JOB POST TRIAGE - full run.

Layer one (layer1.py): plain code kicks out obvious passes.
Layer two (this file): what survives goes to Claude for a real call.

Everything lands in results.csv, then your score is printed.

Run it with:   python triage.py
"""

import csv
import json
import os
import sys
from pathlib import Path

import anthropic

from layer1 import check_posting, load_labels

FOLDER = Path(__file__).parent
MODEL = "claude-sonnet-5"



def load_inputs():
    """Read rules.txt and resume.txt, or stop with a clear message."""
    resume_path = FOLDER / "resume.txt"
    if not resume_path.exists():
        sys.exit("resume.txt not found.\n"
                 "Copy resume.example.txt to resume.txt and fill in your own "
                 "resume, then run this again.")
    rules = (FOLDER / "rules.txt").read_text(encoding="utf-8-sig")
    resume = resume_path.read_text(encoding="utf-8-sig")
    return rules, resume


def build_system_prompt(rules, resume):
    return f"""You screen job postings for one specific job seeker.
Decide APPLY or PASS using HIS rules and HIS resume. Do not be generous.
If a hard-no rule is broken, it is a PASS no matter how good the rest looks.

HIS RULES:
{rules}

HIS RESUME:
{resume}

Reply with JSON only. No markdown, no code fences, no extra words.
Use exactly this shape:
{{"decision": "APPLY or PASS",
 "fit_score": 0 to 100,
 "reasons": ["reason 1", "reason 2", "reason 3"],
 "red_flags": ["any hard-no rules this posting breaks"],
 "resume_bullets": ["bullet to lead with", "second bullet"]}}"""


def ask_claude(client, system_prompt, posting_text):
    """Send one posting to Claude and return its answer as a dict."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"JOB POSTING:\n\n{posting_text}"}],
    )
    # The model may send a thinking block first, so find the text block
    reply = ""
    for block in response.content:
        if block.type == "text":
            reply += block.text
    reply = reply.strip()
    # Just in case it wraps the JSON in code fences
    if reply.startswith("```"):
        reply = reply.strip("`")
        reply = reply[reply.find("{"):]
    return json.loads(reply), response.usage


def main():
    # Normally runs on the practice postings.
    # "python triage.py locked" runs the FINAL TEST on the locked postings.
    final_test = len(sys.argv) > 1 and sys.argv[1] == "locked"
    source = FOLDER / ("locked" if final_test else "postings")
    out_name = "results_final.csv" if final_test else "results.csv"
    if final_test:
        print("FINAL TEST on the locked postings. No changes after this run.\n")

    postings = sorted(source.glob("job*.txt"))
    if not postings:
        sys.exit(f"No postings found in {source.name}/.\n"
                 "Save each posting as job01.txt, job02.txt, and so on. "
                 "(EXAMPLE-job00.txt is skipped on purpose.)")

    rules, resume = load_inputs()
    system_prompt = build_system_prompt(rules, resume)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. See 'Running it' in the README.")
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from your computer

    labels = load_labels()
    rows = []
    input_tokens = output_tokens = 0

    for path in postings:
        job = path.stem
        text = path.read_text(encoding="utf-8-sig")
        is_pass, reason = check_posting(text)

        if is_pass:
            # Layer one handled it. No AI needed, no cost.
            row = {"job": job, "decision": "PASS", "fit_score": 0,
                   "reasons": reason, "red_flags": reason,
                   "resume_bullets": "", "decided_by": "layer1 code"}
        else:
            try:
                answer, usage = ask_claude(client, system_prompt, text)
                input_tokens += usage.input_tokens
                output_tokens += usage.output_tokens
                row = {"job": job,
                       "decision": answer["decision"].upper(),
                       "fit_score": answer["fit_score"],
                       "reasons": " | ".join(answer["reasons"]),
                       "red_flags": " | ".join(answer["red_flags"]),
                       "resume_bullets": " | ".join(answer["resume_bullets"]),
                       "decided_by": "claude"}
            except Exception as error:
                # Keep the row. Dropping it would quietly shrink the
                # denominator and make the agreement score look better.
                print(f"{job}: something went wrong -> {error}")
                row = {"job": job, "decision": "ERROR", "fit_score": "",
                       "reasons": f"no answer: {error}", "red_flags": "",
                       "resume_bullets": "", "decided_by": "error"}

        row["my_label"] = labels.get(job, "?")
        row["match"] = "yes" if row["decision"] == row["my_label"] else "NO"
        rows.append(row)
        print(f"{job}  you: {row['my_label']:5} tool: {row['decision']:5} "
              f"score: {row['fit_score']!s:>3}  match: {row['match']}")

    # Save every row so you can open it in Google Sheets
    out = FOLDER / out_name
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # Score it. The two kinds of mistakes are not equally bad.
    matched = sum(1 for r in rows if r["match"] == "yes")
    false_apply = [r["job"] for r in rows
                   if r["decision"] == "APPLY" and r["my_label"] == "PASS"]
    false_pass = [r["job"] for r in rows
                  if r["decision"] == "PASS" and r["my_label"] == "APPLY"]
    failed = [r["job"] for r in rows if r["decision"] == "ERROR"]

    cost = input_tokens / 1_000_000 * 2 + output_tokens / 1_000_000 * 10

    print()
    print(f"Agreed with you: {matched} of {len(rows)}")
    print(f"Said APPLY, you said PASS (wasted time): {len(false_apply)}  {false_apply}")
    print(f"Said PASS, you said APPLY (missed job):  {len(false_pass)}  {false_pass}")
    print(f"No answer from Claude (counted as wrong): {len(failed)}  {failed}")
    print(f"Saved to {out.name}")
    print(f"Rough cost this run: ${cost:.3f}")


if __name__ == "__main__":
    main()
