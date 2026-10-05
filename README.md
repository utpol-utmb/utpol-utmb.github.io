# PhD Mentor Finder

A free website that helps students find PhD and Master's supervisors who are taking students, funded positions, and scholarships. It updates itself every day from official sources.

## How it works (no server, no approvals)

```
Every day at 05:17 UTC GitHub runs .github/workflows/update-and-deploy.yml on its own servers:
  1. pipeline/build.py collects data (every request first checks the site's robots.txt)
       - NIH RePORTER, NSF Award Search, UKRI Gateway to Research   -> supervisors with active grants
       - (switched off until listed on Play) ARC grants, EURAXESS PhD-level adverts
       - data/curated/positions.json and scholarships.json            -> hand-checked items
       - OpenAlex                                                    -> recent papers, topics, university website
  2. Tags everything with the Field > Subfield tree in pipeline/taxonomy.yaml
  3. Writes site/data/* and site/data/health.json, commits them, publishes the site
  4. pipeline/report_health.py opens a GitHub issue labelled "data-health" if a source
     fails or returns nothing (and closes it when all is well again)
```

Safety: a failing source keeps its last good copy. If supervisors, positions or scholarships
collapse compared with yesterday, nothing is published (the site keeps yesterday's data) and
the issue says why. The Monday Claude scheduled task only reads health.json and the issue;
it does not browse websites (except at most ~10 official scholarship pages the robot flagged).

## Subject tree (edit pipeline/taxonomy.yaml)

Fields > Subfields, based on the OpenAlex classification. Each subfield lists OpenAlex subfield
codes (used to tag researchers from their own papers), keywords (used for grant titles and
adverts) and 1-2 search terms (sent to the grant databases). To add a field or subfield, copy a
block and change the ids; the tests check that every OpenAlex code is real. Anything that fits
no subfield lands in the field's "General" bucket, and anything that fits no field in "Other".

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
| Update the US PhD program guide | Edit `data/curated/us_programs.json` (one block per program; copy facts only from official .edu pages, set `checked` to today, write "Not stated…" rather than guess). The daily run flags programs whose official page changed or whose deadline passed in `health.json`. To re-read pages, list URLs in a JSON file and run **Actions → Fetch official pages** (texts land on branch `page-texts`). |
| Add a subject | Edit `pipeline/taxonomy.yaml` (copy a subfield block) |
| Search extra topics | Add words under `extra_search_keywords` in `pipeline/config.yaml` |
| Turn a source off | Set it to `false` under `sources` in `pipeline/config.yaml` |
| See if updates worked | **Actions** tab: green tick = fine, red cross = open it and ask Claude to read the log |
| Build a new Android version | **Actions → Build Android app → Run workflow**, then download from **Releases** |

## What students can do in the app

- Search and filter supervisors, funded positions and scholarships.
- **My preferences**: set subject, degree, where to study and citizenship once; the app opens on them.
- **My list**: star items, give each a status (Interested → Contacted → Applied → Interview → Offer) and a private note; download the list as CSV.
- **Browse by field**: field chips plus Field and Subfield filters; filters for country, degree, funding, deadline and "open to international applicants".
- **Saved searches**: "Save this search" on any tab; My list shows how many new matches appeared since you last opened each one (worked out on the phone, no notifications server).
- **Supervisor pages**: subjects, research topics, 3 recent papers, active funding, open positions, a link that searches only their university's website for their official profile, a contact guide and an email-draft helper (nothing typed there leaves the phone).
- **Deadline reminders**: add any deadline to the phone calendar (.ics with reminders 7 days and 1 day before) or Google Calendar; a strip shows deadlines in My list for the next 30 days.
- **Share** any item as a link (`#item=positions:<id>`), and **report an error / request removal** by email.

Everything above is stored on the user's device only (localStorage keys `pmf-saved`, `pmf-track`, `pmf-profile`, `pmf-searches`, `pmf-me`). There is no server, account or tracking, so the Play data-safety answers stay "no data collected".

## Legal and Play Store checklist (keep when changing anything)

- The app is independent: the footer, About section, privacy page, terms page and the Play Full description (`site/play-assets/full-description.txt`) all say it is not affiliated with NIH, NSF, UKRI or any government, university or scholarship programme.
- Every government data source must be named with its official link in the Play description and in the app. **If you add a new source** (e.g. ERC, ARC, NSERC), add it to: `site/index.html` (#disclaimer), `site/privacy.html`, `site/terms.html` and `full-description.txt`, then paste the new description into Play Console.
- To switch on ARC or EURAXESS: set it to `true` in `pipeline/config.yaml` only after the Play description lists it (the in-app disclaimer adds it automatically when the source is on).
- Never use agency logos or names in the app title, icon or screenshots.
- Sources removed for legal reasons (do not re-add): Nature Careers job feed (robots.txt), FindAPhD, Academic Positions, ScholarshipDB (block bots), ORCID API (robots.txt), CORDIS downloads (robots.txt). jobs.ac.uk refused permission on 5 Oct 2026 to republish its adverts (we may only link to its search page); its name stays in `hold_sources` as a block. The app links to these sites' own search pages instead.
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
