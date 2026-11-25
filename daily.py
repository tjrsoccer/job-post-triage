"""
DAILY RUN: screen today's new postings and send only the Apply results.

    python daily.py                 # screen new postings, write the report, send nothing
    python daily.py --email         # ...and email the Apply results
    python daily.py --dry-run       # skip the Claude call, fake every answer (for testing)

Where postings come from:
    inbox/*.txt, one posting per file. The job-pulling step drops files
    here. The file name (without .txt) is the posting's id, so the same
    posting pulled twice is only screened once.

What it writes:
    reports/YYYY-MM-DD.csv   only the postings worth applying to
    reports/YYYY-MM-DD.html  the same thing as a readable email body
    state/seen.txt           ids already screened, one per line

The screening itself is unchanged: layer1.py first, then the same Claude
prompt triage.py uses. This file only adds "what's new", "keep the
Apply ones", and "send them".
"""

import argparse
import csv
import html
import os
import re
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from layer1 import check_posting

FOLDER = Path(__file__).parent
INBOX = FOLDER / "inbox"
REPORTS = FOLDER / "reports"
SEEN_FILE = FOLDER / "state" / "seen.txt"

COLUMNS = ["date", "id", "title", "company", "location", "pay", "url",
           "fit_score", "reasons", "red_flags", "resume_bullets"]


# ---------------------------------------------------------------------------
# What counts as "worth sending"
# ---------------------------------------------------------------------------

def should_send(row):
    """Decide whether one screened posting goes in today's email/sheet.

    `row` has decision ("APPLY"/"PASS"), fit_score (0-100), and red_flags
    (a string; long shots contain "long shot").

    GUESS: send every APPLY, including long shots (capped at 50), because
    the README says you want to try those anyway. Change this if you'd
    rather only see, say, fit_score >= 60, or keep long shots out.
    """
    return row["decision"] == "APPLY"


# ---------------------------------------------------------------------------
# Reading postings
# ---------------------------------------------------------------------------

FIELD_LINE = re.compile(r"^(company|location|pay|salary|url|link)\s*:\s*(.+)$",
                        re.IGNORECASE)


def read_header(text):
    """Pull title / company / location / pay / url out of a posting.

    GUESS at the file format (to be matched with the job-pulling step):
    the first non-blank line is the title, and lines like "Company: ..."
    or "URL: ..." near the top fill in the rest. Anything missing stays
    blank; the screen still works on the full text either way.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    info = {"title": lines[0] if lines else "", "company": "",
            "location": "", "pay": "", "url": ""}
    for line in lines[1:15]:
        match = FIELD_LINE.match(line)
        if match:
            key = match.group(1).lower()
            key = {"salary": "pay", "link": "url"}.get(key, key)
            info[key] = info[key] or match.group(2).strip()
    return info


def load_seen():
    if not SEEN_FILE.exists():
        return set()
    return {line.strip() for line in SEEN_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()}


def save_seen(seen):
    SEEN_FILE.parent.mkdir(exist_ok=True)
    SEEN_FILE.write_text("\n".join(sorted(seen)) + "\n", encoding="utf-8")


def new_postings(seen):
    """Inbox files we have not screened before, oldest name first."""
    if not INBOX.exists():
        return []
    return [p for p in sorted(INBOX.glob("*.txt")) if p.stem not in seen]


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

def fake_answer(text):
    """--dry-run stand-in for Claude, so the pipeline can be tested for free."""
    return {"decision": "APPLY", "fit_score": 70,
            "reasons": ["dry run: not really screened"],
            "red_flags": [], "resume_bullets": []}, None


def screen(path, dry_run):
    """Return a row dict for one posting. Raises if Claude's answer is unusable."""
    text = path.read_text(encoding="utf-8-sig")
    row = {"date": date.today().isoformat(), "id": path.stem, **read_header(text)}

    is_pass, reason = check_posting(text)
    if is_pass:
        row.update(decision="PASS", fit_score=0, reasons=reason,
                   red_flags=reason, resume_bullets="")
        return row

    if dry_run:
        answer, _ = fake_answer(text)
    else:
        # Imported here so --dry-run works without an API key or resume.txt
        from triage import ask_claude
        answer, _ = ask_claude(text)

    row.update(decision=str(answer["decision"]).upper(),
               fit_score=int(answer["fit_score"]),
               reasons=" | ".join(answer["reasons"]),
               red_flags=" | ".join(answer["red_flags"]),
               resume_bullets=" | ".join(answer["resume_bullets"]))
    return row


# ---------------------------------------------------------------------------
# Report and delivery
# ---------------------------------------------------------------------------

def write_csv(rows, out):
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_html(rows, screened, errors):
    esc = html.escape
    parts = [f"<p>{len(rows)} to apply to, out of {screened} new postings screened.</p>"]
    for r in sorted(rows, key=lambda r: -r["fit_score"]):
        title = esc(r["title"] or r["id"])
        if r["url"]:
            title = f'<a href="{esc(r["url"])}">{title}</a>'
        where = " · ".join(esc(x) for x in (r["company"], r["location"], r["pay"]) if x)
        parts.append(
            f"<h3>{title} <small>(fit {r['fit_score']})</small></h3>"
            + (f"<p>{where}</p>" if where else "")
            + f"<p><b>Why:</b> {esc(r['reasons'])}</p>"
            + (f"<p><b>Watch out:</b> {esc(r['red_flags'])}</p>" if r["red_flags"] else "")
            + (f"<p><b>Lead with:</b> {esc(r['resume_bullets'])}</p>"
               if r["resume_bullets"] else "")
        )
    if errors:
        # Never drop a posting silently: list the ones that failed.
        parts.append("<hr><p><b>Could not screen (will retry tomorrow):</b> "
                     + esc(", ".join(errors)) + "</p>")
    return "\n".join(parts)


def send_email(subject, body_html, attachment):
    """Send through Gmail SMTP with an app password.

    Needs these environment variables:
        SMTP_USER          your Gmail address
        SMTP_APP_PASSWORD  a Google app password (not your real password)
        DAILY_TO           where to send it (defaults to SMTP_USER)
    """
    user = os.environ["SMTP_USER"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = os.environ.get("DAILY_TO", user)
    msg.set_content("Open this email in an HTML-capable mail app.")
    msg.add_alternative(body_html, subtype="html")
    msg.add_attachment(attachment.read_bytes(), maintype="text",
                       subtype="csv", filename=attachment.name)
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), 465) as smtp:
        smtp.login(user, os.environ["SMTP_APP_PASSWORD"])
        smtp.send_message(msg)


# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--email", action="store_true", help="email the Apply results")
    parser.add_argument("--dry-run", action="store_true",
                        help="don't call Claude; fake every answer")
    args = parser.parse_args(argv)

    seen = load_seen()
    todo = new_postings(seen)
    print(f"{len(todo)} new postings in {INBOX.name}/")
    if not todo:
        # Leave any earlier report from today alone.
        return 0

    keep, errors = [], []
    for path in todo:
        try:
            row = screen(path, args.dry_run)
        except Exception as error:
            # Not marked as seen, so tomorrow's run tries it again.
            print(f"{path.stem}: could not screen -> {error}")
            errors.append(path.stem)
            continue
        if not args.dry_run:
            seen.add(path.stem)
        print(f"{path.stem}  {row['decision']:5} {row['fit_score']:3}  {row['title'][:60]}")
        if should_send(row):
            keep.append(row)

    REPORTS.mkdir(exist_ok=True)
    today = date.today().isoformat()
    csv_path = REPORTS / f"{today}.csv"
    html_path = REPORTS / f"{today}.html"
    write_csv(keep, csv_path)
    html_path.write_text(build_html(keep, len(todo), errors), encoding="utf-8")
    save_seen(seen)

    print(f"\n{len(keep)} to apply to. Report: {csv_path.relative_to(FOLDER)}")

    # GUESS: no email on a day with nothing to apply to and no errors,
    # so a quiet day doesn't land in your inbox.
    if args.email and (keep or errors):
        subject = f"Job triage {today}: {len(keep)} to apply to"
        send_email(subject, html_path.read_text(encoding="utf-8"), csv_path)
        print(f"Emailed to {os.environ.get('DAILY_TO', os.environ['SMTP_USER'])}")

    return 1 if errors and not keep and len(errors) == len(todo) else 0


if __name__ == "__main__":
    sys.exit(main())
