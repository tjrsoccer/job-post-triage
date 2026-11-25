# Job Post Triage Assistant

A tool that reads a job posting, checks it against my own written rules and
my resume, and says Apply or Pass with reasons.

## Why I built it

An auto-apply tool once submitted about 54 applications for me to jobs I
wasn't a fit for. This is the opposite idea. Instead of applying to more
jobs faster, it decides which ones are worth applying to at all, and it
gets graded against my own judgment.

## How it works

Two layers.

**Layer one is plain Python, no AI.** It looks at the job title and kicks
out obvious misses: engineer, scientist, developer, researcher, senior,
staff, manager, and pay red flags like commission-only. It only looks at
titles, because job postings often mention "engineers" as teammates and a
simple keyword search rejected good jobs. If layer one isn't sure, it
passes the posting along. A wrong rejection here is expensive: that job
never reaches the AI. A wrong "send it on" costs about a penny.

**Layer two is the Claude API.** Everything that survives layer one goes to
Claude with my rules and my resume. It returns JSON: Apply or Pass, a fit
score from 0 to 100, three reasons, any red flags, and the two resume
bullets I should lead with. Every row lands in a CSV.

Keeping the deterministic rules in front of the model is cheaper and more
predictable than asking the model to do everything.

## How I measured it

1. Collected 20 real job postings and saved each as a text file.
2. Labeled every one myself, Apply or Pass with a one-line reason, **before
   any code ran**.
3. Randomly moved 6 into a locked folder as a final test and didn't touch
   them again.
4. Tuned the prompt and rules on the other 14.
5. Ran the final version once on the 6 locked postings.

I tracked the two kinds of mistakes separately, because they aren't equally
bad. A false apply wastes an hour. A missed job is gone for good.

## Results

| Version | Set | Agreed with me | False applies | Missed jobs |
|---------|-----|----------------|---------------|-------------|
| v1 | 14 practice | 12 of 14 | 0 | 2 |
| v2 | 14 practice | 14 of 14 | 0 | 0 |
| Final | 6 locked | 6 of 6 | 0 | 0 |

Cost: about 10 cents per run of 14 postings.

## What went wrong, and what I changed

**v1 missed two jobs.** Both were AI red teaming programs that required a CS
degree or current enrollment. The tool was right by my rules, which said any
degree requirement is an automatic Pass. I was the one being inconsistent: I
still wanted to apply to those.

So I changed the rule, not my labels. A degree or enrollment requirement on
its own is no longer an automatic Pass. If nothing else on the hard-no list
is broken, it's an Apply with the fit score capped at 50 and a "long shot"
red flag. If the degree requirement comes with another hard no, like an
engineer title, it's still a Pass.

Fixing the labels to match the tool would have made the score meaningless.

**A bug worth mentioning:** the first live run crashed because the API
returned a thinking block before the text block, and my code grabbed the
first block blindly. Now it looks for the text block by type.

## Limitations

- 20 postings is a small sample, and 6 in the final test is smaller. All 6
  agreeing is a good sign, not proof.
- The answer key is my own judgment, so the tool is measured on matching me,
  not on whether I'm right about which jobs to apply to.
- Most of my Pass postings were obvious ones like engineer titles. The tool
  hasn't been tested much on close calls.
- It only finds jobs on the sources set up in `fetch_config.json`.

## What I'd do next

- Add 30 more postings, weighted toward close calls: ops roles wanting 3
  years, hybrid roles just outside my commute, "preferred" versus "required"
  wording.
- Track how my own Apply decisions turn out, so the rules get graded against
  real outcomes and not just my gut.
- Report false applies and missed jobs separately over a larger set.

## Pulling new postings automatically

`fetch_jobs.py` drops new postings into `inbox/`, one text file each
(`inbox/<source>-<id>.txt`, title on the first line). `seen.json`
remembers every posting ever saved, so the same job is never written
twice, even if it comes back under a new id. Both are kept out of git.

```
python fetch_jobs.py                       # Greenhouse + Lever boards
python fetch_jobs.py indeed-import a.md    # Indeed postings (see below)
python -m unittest discover tests
```

- **Greenhouse and Lever** have free public job-board feeds, so this is
  plain Python. List the company slugs in `fetch_config.json`. Postings
  outside the Seattle-area cities or remote are skipped; anything unclear
  is kept, because the screener checks location again.
- **Indeed** has no public API a script can call. Indeed postings come
  from the Indeed connector in Claude: a Claude task runs the searches in
  `fetch_config.json`, saves each job's details to a file, and passes the
  files to `indeed-import`, which handles naming and dedupe.

## Running it

```
pip install anthropic
setx ANTHROPIC_API_KEY "your-key"
python triage.py          # practice postings
python triage.py locked   # final test
```

## What is not in this repo

- **The 20 job postings.** They are full job descriptions from real
  companies, so republishing them word for word isn't mine to do. The
  folder structure and one made-up example posting are here instead.
- **My resume.** `resume.example.txt` shows the shape. Copy it to
  `resume.txt` and fill in your own to run the tool.
- **My API key.** It lives in an environment variable on my computer, not
  in any file here.

Because of that, the numbers below can't be reproduced from this repo
alone. The code, rules, labels, and method are all here.

## Files

- `rules.txt` - my hard-no list, long-shot rule, and good-fit signals
- `resume.example.txt` - the shape of the resume file the tool reads
- `postings/` - practice postings (one made-up example here)
- `locked/` - final test postings (not in this repo)
- `my_labels.txt` - my own calls, written before any code ran
- `layer1.py` - plain-code filter
- `triage.py` - full run, writes the CSV and prints the score
- `fetch_jobs.py` - pulls new postings into `inbox/`
- `fetch_config.json` - searches, job boards and cities to pull from
