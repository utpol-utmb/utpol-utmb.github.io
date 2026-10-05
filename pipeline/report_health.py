"""Open, update or close the GitHub issue that tracks data problems.

Run by the daily workflow after the build:
    python pipeline/report_health.py [path/to/health.json]

One rolling issue labelled `data-health`:
  * problems today and no open issue  -> open one (GitHub emails the repo owner)
  * problems today and an open issue  -> add a comment only if the problem list changed
  * no problems and an open issue      -> comment "all clear" and close it
Scholarship pages waiting for review are listed but never open an issue on their own;
the weekly Claude check handles those.
Needs GITHUB_TOKEN and GITHUB_REPOSITORY (set automatically inside GitHub Actions).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import requests

API = "https://api.github.com"
LABEL = "data-health"


def body_for(h: dict) -> str:
    lines = [f"**Daily data run {h['generated_at']}: {h['overall'].upper()}**", ""]
    if h.get("aborted"):
        lines += [f"Publishing was stopped: {h['aborted']}. The site still shows yesterday's data.", ""]
    if h.get("warnings"):
        lines += ["Problems:"] + [f"- {w}" for w in h["warnings"]] + [""]
    lines += ["| Source | Status | Records | Last OK |", "|---|---|---|---|"]
    for name, s in sorted(h.get("sources", {}).items()):
        lines.append(f"| {name} | {s.get('status')} | {s.get('count', '')} | {s.get('last_ok', '')} |")
    if h.get("scholarships_to_review"):
        lines += ["", "Scholarship pages for the weekly check:"] + [f"- {r['name']}: {r['reason']}" for r in h["scholarships_to_review"]]
    lines += ["", "What to do: usually nothing; a failing source keeps its last good copy. If a source fails for "
              "several days, open the latest run under Actions and ask Claude to read the log."]
    return "\n".join(lines)


def main() -> int:
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "site/data/health.json")
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not path.exists():
        print("no health.json; nothing to report")
        return 0
    h = json.loads(path.read_text())
    problems = bool(h.get("warnings") or h.get("aborted"))
    if not token or not repo:
        print(body_for(h))
        return 0
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    s.post(f"{API}/repos/{repo}/labels", json={"name": LABEL, "color": "d93f0b", "description": "Daily data run problems"})
    open_issues = s.get(f"{API}/repos/{repo}/issues", params={"labels": LABEL, "state": "open"}).json()
    issue = open_issues[0] if isinstance(open_issues, list) and open_issues else None
    body = body_for(h)
    if problems and not issue:
        r = s.post(f"{API}/repos/{repo}/issues", json={"title": "Data health: a source needs attention", "body": body, "labels": [LABEL]})
        print("opened issue", r.status_code)
    elif problems and issue:
        sig = "\n".join(sorted(h.get("warnings", [])))
        if sig not in (issue.get("body") or "") and not any(sig in (c.get("body") or "") for c in s.get(issue["comments_url"]).json()[-3:]):
            s.post(issue["comments_url"], json={"body": body})
            print("commented on issue", issue["number"])
    elif not problems and issue:
        s.post(issue["comments_url"], json={"body": f"All sources healthy on {h['generated_at']}. Closing."})
        s.patch(f"{API}/repos/{repo}/issues/{issue['number']}", json={"state": "closed"})
        print("closed issue", issue["number"])
    else:
        print("all healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
