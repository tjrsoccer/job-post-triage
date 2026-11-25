"""
FETCH: pull new job postings into inbox/ so the screener can read them.

Each new posting becomes one plain-text file, inbox/<source>-<id>.txt:

    <job title>
    Company: ...
    Location: ...
    Pay: ...
    Posted: ...
    URL: ...
    Source: ...

    <full description>

seen.json remembers every posting ever saved, so the same job is never
written twice, even after you delete or move files out of inbox/.

Two ways in:

  python fetch_jobs.py
      Pulls the public Greenhouse and Lever job boards listed in
      fetch_config.json. Plain Python, no API key, no AI.

  python fetch_jobs.py indeed-import FILE [FILE ...]
      Saves Indeed postings. Indeed has no public API a script can call,
      so Indeed results come from the Indeed connector in Claude: a Claude
      task runs the search, saves each job's details to a file, and hands
      the files to this command. This command does the naming and dedupe.
"""

import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

FOLDER = Path(__file__).parent
INBOX = FOLDER / "inbox"
SEEN_FILE = FOLDER / "seen.json"
CONFIG_FILE = FOLDER / "fetch_config.json"


# ---------------------------------------------------------------- dedupe

def load_seen():
    if SEEN_FILE.exists():
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    return {}


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(seen, indent=2, sort_keys=True), encoding="utf-8")


def fingerprint(title, company, location):
    """Same title + company + location = same job, even if the id changed.

    Catches a job reposted under a new id, or listed on two sources.
    """
    raw = "|".join(re.sub(r"\W+", " ", s or "").strip().lower()
                   for s in (title, company, location))
    return "fp-" + hashlib.sha1(raw.encode()).hexdigest()[:12]


def safe_id(text):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-")[:60]


def save_posting(seen, source, job_id, title, company, location,
                 description, url="", pay="", posted=""):
    """Write one posting to inbox/ unless it was seen before.

    Returns the new file's path, or None if it was a repeat.
    """
    key = f"{source}-{safe_id(job_id)}"
    fp = fingerprint(title, company, location)
    if key in seen or fp in seen:
        return None

    INBOX.mkdir(exist_ok=True)
    path = INBOX / f"{key}.txt"
    lines = [
        title.strip(),
        f"Company: {company}",
        f"Location: {location}",
        f"Pay: {pay or 'not listed'}",
        f"Posted: {posted or 'not listed'}",
        f"URL: {url}",
        f"Source: {source}",
        "",
        description.strip(),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    today = date.today().isoformat()
    seen[key] = {"title": title, "company": company, "saved": today}
    seen[fp] = key
    return path


# ---------------------------------------------------------------- filters

def is_wanted_location(location, config):
    """Rule 9: Seattle area or remote. Unsure? Keep it.

    The screener checks rule 9 again with the full text, so a loose
    filter here only costs a penny. A strict one could hide a good job.
    """
    loc = (location or "").lower()
    if not loc:
        return True
    if "remote" in loc and config.get("allow_remote", True):
        return True
    return any(city.lower() in loc for city in config.get("cities", []))


def is_wanted_title(title, config):
    """Optional: only keep titles with one of title_keywords. Empty = keep all."""
    words = config.get("title_keywords", [])
    return not words or any(w.lower() in title.lower() for w in words)


# ---------------------------------------------------------------- boards

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "job-post-triage"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def html_to_text(raw):
    """Greenhouse and Lever send HTML. The screener wants plain text."""
    text = html.unescape(raw or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)  # Greenhouse double-escapes its content
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def greenhouse_jobs(board):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    for job in data.get("jobs", []):
        yield {
            "job_id": f"{board}-{job['id']}",
            "title": job.get("title", ""),
            "company": board,
            "location": (job.get("location") or {}).get("name", ""),
            "description": html_to_text(job.get("content", "")),
            "url": job.get("absolute_url", ""),
            "posted": (job.get("updated_at") or "")[:10],
        }


def lever_jobs(company):
    data = get_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
    for job in data:
        cats = job.get("categories") or {}
        location = cats.get("location", "")
        if job.get("workplaceType") == "remote" and "remote" not in location.lower():
            location = f"{location} (Remote)".strip()
        parts = [job.get("descriptionPlain", "")]
        for section in job.get("lists", []):
            parts.append(section.get("text", ""))
            parts.append(html_to_text(section.get("content", "")))
        parts.append(job.get("additionalPlain", ""))
        pay = job.get("salaryRange") or {}
        yield {
            "job_id": f"{company}-{job['id']}",
            "title": job.get("text", ""),
            "company": company,
            "location": location,
            "description": "\n\n".join(p for p in parts if p),
            "url": job.get("hostedUrl", ""),
            "pay": (f"{pay.get('min')} - {pay.get('max')} {pay.get('currency', '')}"
                    if pay.get("min") else ""),
        }


def pull_boards(config, seen):
    sources = [("greenhouse", b, greenhouse_jobs) for b in config.get("greenhouse_boards", [])]
    sources += [("lever", c, lever_jobs) for c in config.get("lever_companies", [])]
    new = 0
    for source, name, fetch in sources:
        try:
            jobs = list(fetch(name))
        except Exception as error:
            # One dead board should not stop the rest
            print(f"{source} {name}: could not fetch -> {error}")
            continue
        kept = 0
        for job in jobs:
            if not is_wanted_location(job["location"], config):
                continue
            if not is_wanted_title(job["title"], config):
                continue
            if save_posting(seen, source, **job):
                kept += 1
        print(f"{source} {name}: {len(jobs)} listed, {kept} new saved")
        new += kept
    return new


# ---------------------------------------------------------------- indeed

FIELD = r"\*\*{}:\*\*\s*(.+)"


def parse_indeed(text):
    """Read one job from the Indeed connector's get_job_details output."""
    def field(name):
        m = re.search(FIELD.format(re.escape(name)), text)
        return m.group(1).strip() if m else ""

    title_match = re.search(r"^\s*#+\s*(.+)$", text, flags=re.MULTILINE)
    # The description is everything after the last **Field:** line
    last_field = list(re.finditer(r"^\s*\*\*[^*]+:\*\*.*$", text, flags=re.MULTILINE))
    description = text[last_field[-1].end():] if last_field else text
    description = "\n".join(line.strip() for line in description.splitlines())

    return {
        "job_id": field("Job Id") or field("Job ID"),
        "title": title_match.group(1).strip() if title_match else field("Job Title"),
        "company": field("Company"),
        "location": field("Location"),
        "pay": field("Compensation"),
        "posted": field("Posted on"),
        "url": field("View Job URL"),
        "description": description,
    }


def import_indeed(files, seen):
    new = 0
    for name in files:
        job = parse_indeed(Path(name).read_text(encoding="utf-8-sig"))
        if not job["title"] or not job["job_id"]:
            print(f"{name}: could not find a title and job id, skipped")
            continue
        path = save_posting(seen, "indeed", **job)
        print(f"{name}: {'saved ' + path.name if path else 'already seen'}")
        new += bool(path)
    return new


# ---------------------------------------------------------------- main

def main():
    seen = load_seen()
    if len(sys.argv) > 1 and sys.argv[1] == "indeed-import":
        new = import_indeed(sys.argv[2:], seen)
    else:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        new = pull_boards(config, seen)
    save_seen(seen)
    print(f"\n{new} new posting(s) in {INBOX.name}/")


if __name__ == "__main__":
    main()
