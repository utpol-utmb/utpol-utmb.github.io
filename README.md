# PhD Mentor Finder

A free website that helps students find PhD and Master's supervisors who are taking students, funded positions, and scholarships. It updates itself every day from official sources.

## How it works (no server needed)

```
Every day at 05:17 UTC, GitHub runs the robot (.github/workflows/update-and-deploy.yml):
  1. pipeline/build.py collects data
       - NSF awards API          -> US supervisors with active grants
       - NIH RePORTER API        -> US health supervisors, incl. T32 training grants
       - UKRI Gateway to Research -> UK supervisors with active grants
       - Job-board RSS feeds      -> open PhD/Master's positions
       - data/curated/*.json      -> hand-checked positions and scholarships
       - OpenAlex API             -> papers, citations, h-index, topics, ORCID
  2. It merges, removes duplicates and expired deadlines, and labels each supervisor:
       Hiring now  >  Funds students (training grant)  >  Active grant
  3. It saves site/data/*.json and publishes the site/ folder to GitHub Pages.
```

If any one source fails, the last good copy of that source is reused. If the total number of records suddenly falls by more than 60%, nothing is published and GitHub emails you.

## Where it lives

- Website: https://utpol-utmb.github.io/ (GitHub Pages, free)
- Code: https://github.com/utpol-utmb/utpol-utmb.github.io
- Android app: built by the "Build Android app" workflow; each signed build appears under **Releases** as `app-release.aab` (for Google Play) and `app-release.apk` (direct install for testers).
- A weekly Claude scheduled task (Mondays) checks the sources, adds newly found positions and refreshes scholarship deadlines.

## Everyday editing (no coding)

| You want to… | Do this on GitHub |
|---|---|
| Add a scholarship | Edit `data/curated/scholarships.json`, copy an existing block, change the values |
| Add a position | Edit `data/curated/positions.json` the same way, or turn on the Google Sheet option in `config.yaml` |
| Search new topics | Add words under `search_keywords` in `pipeline/config.yaml` |
| Turn a source off | Set it to `false` under `sources` in `pipeline/config.yaml` |
| See if updates worked | **Actions** tab: green tick = fine, red cross = open it and ask Claude to read the log |
| Build a new Android version | **Actions → Build Android app → Run workflow**, then download from **Releases** |

## Rules this project follows

- Only official or public sources, each record links to its source.
- No LinkedIn or other sites whose terms forbid automated collection.
- No personal email addresses are stored; students contact supervisors via university pages.
- Scholarship amounts and deadlines show whether they were confirmed on the official page.

## For developers

```
pip install -r pipeline/requirements.txt
python pipeline/build.py --offline   # sample data, no internet
python pipeline/build.py             # live
python -m pytest -q tests
cd site && python -m http.server     # open http://localhost:8000
```
