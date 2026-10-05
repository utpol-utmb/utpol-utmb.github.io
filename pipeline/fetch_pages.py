"""Fetch official pages listed in a JSON file and save their visible text (for building curated guides).

    python pipeline/fetch_pages.py data/curated/us_programs_urls.json /tmp/pages

Each request goes through the Http helper, so robots.txt is honoured. Output: one .txt per URL
plus index.json with status codes. Used by the manual "Fetch official pages" workflow.
"""
from __future__ import annotations

import hashlib
import html
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Http  # noqa: E402


def visible_text(page: str) -> str:
    page = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<(br|/p|/li|/h\d|/tr|/div)[^>]*>", "\n", page, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def main() -> int:
    urls = json.loads(pathlib.Path(sys.argv[1]).read_text())
    out = pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    http = Http("utpol.dnet@gmail.com", pause=1.0)
    index = []
    for item in urls:
        url = item["url"] if isinstance(item, dict) else item
        key = hashlib.sha1(url.encode()).hexdigest()[:10]
        try:
            r = http._do("GET", url, allow_redirects=True)
            txt = visible_text(r.text)
            (out / f"{key}.txt").write_text(f"URL: {url}\nFINAL: {r.url}\n\n{txt[:60000]}")
            index.append({"url": url, "key": key, "status": r.status_code, "chars": len(txt)})
        except Exception as ex:  # noqa: BLE001
            index.append({"url": url, "key": key, "status": "error", "error": str(ex)[:200]})
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(json.dumps(index, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
