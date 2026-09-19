"""
LAYER ONE: plain code, no AI.

Catches only OBVIOUS passes, based on the job TITLE.
If it isn't sure, it sends the posting on to the AI (layer two).

Why so careful? A wrong PASS here means a good job gets skipped
and the AI never even sees it. A wrong "send to AI" only costs
about a penny.
"""

import re
from pathlib import Path

FOLDER = Path(__file__).parent

# Words that make a title a hard no (rules 2 and 5 in rules.txt)
TITLE_WORDS = r"(engineer|scientist|developer|researcher|manager|director)"
SENIOR_WORDS = r"(senior|staff|principal|lead|head of)"

# Places where a job title usually shows up:
#   "As a Senior Machine Learning Engineer, you will..."
#   "We are looking for a Staff Software Engineer..."
#   "We are seeking a Data Scientist..."
TITLE_SPOTS = [
    r"\bas an? ([^,.\n]{0,60})",
    r"\b(?:looking for|seeking|hiring) an? ([^,.\n]{0,60})",
]

# Pay rules (rules 7 and 8). These phrases are rare, but always a no.
PAY_PHRASES = [
    "commission only", "commission-only", "100% commission",
    "unpaid", "equity only", "equity-only",
]


def find_titles(text):
    """Return the likely job titles found in a posting."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    titles = []
    # The first line of a posting is often the title itself
    if lines and len(lines[0]) <= 80:
        titles.append(lines[0])
    for pattern in TITLE_SPOTS:
        titles += re.findall(pattern, text, flags=re.IGNORECASE)
    return titles


def check_posting(text):
    """Return (True, reason) for an obvious pass, or (False, "") if unsure."""
    for title in find_titles(text):
        # Singular only: "Engineer" is a title, "engineers" is a teammate
        if re.search(rf"\b{TITLE_WORDS}\b(?!s)", title, flags=re.IGNORECASE):
            return True, f"hard-no title: {title.strip()}"
        if re.search(rf"\b{SENIOR_WORDS}\b", title, flags=re.IGNORECASE):
            return True, f"senior title: {title.strip()}"

    lowered = text.lower()
    for phrase in PAY_PHRASES:
        if phrase in lowered:
            return True, f"pay rule: {phrase}"

    return False, ""


def load_labels():
    """Read my_labels.txt into a dict like {'job01': 'APPLY'}."""
    labels = {}
    for line in (FOLDER / "my_labels.txt").read_text(encoding="utf-8-sig").splitlines():
        parts = [p.strip() for p in line.split("|")]
        # Real label lines start with jobNN (the examples are indented)
        if len(parts) >= 2 and re.fullmatch(r"job\d\d", parts[0]) and not line.startswith(" "):
            labels[parts[0]] = parts[1].upper()
    return labels


if __name__ == "__main__":
    labels = load_labels()
    mistakes = 0
    for path in sorted((FOLDER / "postings").glob("job*.txt")):
        job = path.stem
        is_pass, reason = check_posting(path.read_text(encoding="utf-8-sig"))
        mine = labels.get(job, "?")
        if is_pass:
            result = "PASS (layer one)"
            if mine == "APPLY":
                mistakes += 1
                reason += "   <-- WRONG, you said APPLY"
        else:
            result = "send to AI"
        print(f"{job}  you: {mine:5}  tool: {result:17} {reason}")

    print()
    print(f"Good jobs wrongly rejected by layer one: {mistakes}  (this must be 0)")
