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

## Deploy it (about 20 minutes, one time)

1. Create a free account at github.com.
2. Click **New repository** → name it `phd-mentor-finder` → Public → Create.
3. Click **uploading an existing file**, drag in everything from this folder (including the hidden `.github` folder), then **Commit changes**.
   *Tip: on Windows, turn on "Show hidden items" in File Explorer to see `.github`.*
4. Go to **Settings → Pages** → under *Build and deployment*, set **Source = GitHub Actions**.
5. Go to **Settings → Actions → General** → *Workflow permissions* → **Read and write** → Save.
6. Go to **Actions** → *Update data and publish site* → **Run workflow**.
7. After about 5 minutes your site is live at `https://YOUR-USERNAME.github.io/phd-mentor-finder/`.
8. Open `pipeline/config.yaml` on GitHub (pencil icon) and change `contact_email` to your email.

## Everyday editing (no coding)

| You want to… | Do this on GitHub |
|---|---|
| Add a scholarship | Edit `data/curated/scholarships.json`, copy an existing block, change the values |
| Add a position | Edit `data/curated/positions.json` the same way, or turn on the Google Sheet option in `config.yaml` |
| Search new topics | Add words under `search_keywords` in `pipeline/config.yaml` |
| Turn a source off | Set it to `false` under `sources` in `pipeline/config.yaml` |
| See if updates worked | **Actions** tab: green tick = fine, red cross = open it and ask Claude to read the log |

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
