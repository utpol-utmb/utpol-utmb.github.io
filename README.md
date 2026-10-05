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

## What students can do in the app

- Search and filter supervisors, funded positions and scholarships.
- **My preferences**: set subject, degree, where to study and citizenship once; the app opens on them.
- **My list**: star items, give each a status (Interested → Contacted → Applied → Interview → Offer) and a private note; download the list as CSV.
- **Deadline reminders**: add any deadline to the phone calendar (.ics with reminders 7 days and 1 day before) or Google Calendar; a strip shows deadlines in My list for the next 30 days.
- **Share** any item as a link (`#item=positions:<id>`), and **report an error / request removal** by email.

Everything above is stored on the user's device only (localStorage keys `pmf-saved`, `pmf-track`, `pmf-profile`). There is no server, account or tracking, so the Play data-safety answers stay "no data collected".

## Legal and Play Store checklist (keep when changing anything)

- The app is independent: the footer, About section, privacy page, terms page and the Play Full description (`site/play-assets/full-description.txt`) all say it is not affiliated with NIH, NSF, UKRI or any government, university or scholarship programme.
- Every government data source must be named with its official link in the Play description and in the app. **If you add a new source** (e.g. ERC, ARC, NSERC), add it to: `site/index.html` (#disclaimer), `site/privacy.html`, `site/terms.html` and `full-description.txt`, then paste the new description into Play Console.
- Never use agency logos or names in the app title, icon or screenshots.
- Show short factual summaries and link out; do not copy full adverts.
- Removal requests: act within 14 days.

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
