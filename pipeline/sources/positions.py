"""Position collectors: job-board RSS feeds and an optional Google Sheet (CSV)."""
from __future__ import annotations

import csv
import io
import re

from common import Http, classify, parse_date, slug

DEGREE_RX = {"Masters": re.compile(r"\b(master'?s?|msc|mphil|m\.sc|mres)\b", re.I),
             "PhD": re.compile(r"\b(phd|ph\.d|doctoral|dphil|doctorate)\b", re.I)}
FUNDED_RX = re.compile(r"(fully[- ]funded|stipend|studentship|salary|scholarship|funded)", re.I)
UNFUNDED_RX = re.compile(r"(self[- ]funded|no funding|unfunded)", re.I)
DEADLINE_RX = re.compile(r"(?:closing date|deadline|apply by|applications close)[:\s]+([0-9]{1,2}\s+\w+\s+20\d\d|20\d\d-\d\d-\d\d|\w+\s+\d{1,2},\s+20\d\d)", re.I)
SUPERVISOR_RX = re.compile(r"(?:supervisor|supervised by|principal investigator|PI)[s]?[:\s]+((?:Dr|Prof|Professor)\.?\s+[A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+){0,2})")


def detect_degree(text: str) -> str:
    p, m = bool(DEGREE_RX["PhD"].search(text)), bool(DEGREE_RX["Masters"].search(text))
    return "PhD or Masters" if p and m else ("Masters" if m else "PhD")


def from_rss(http: Http, feeds: list[dict]) -> tuple[list[dict], dict]:
    import feedparser

    items, status = [], {}
    for f in feeds:
        try:
            raw = http.get_text(f["url"])
            parsed = feedparser.parse(raw)
            n = 0
            for e in parsed.entries:
                title = e.get("title", "")
                desc = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
                text = f"{title} {desc}"
                if not DEGREE_RX["PhD"].search(text) and not DEGREE_RX["Masters"].search(text):
                    continue
                dl = DEADLINE_RX.search(desc)
                sup = SUPERVISOR_RX.search(desc)
                items.append({
                    "id": slug(f["source"], title)[:80],
                    "title": title.strip(),
                    "supervisor": sup.group(1) if sup else "",
                    "university": e.get("author", "") or "",
                    "city": "", "country": f.get("country", ""),
                    "subject_area": classify(text),
                    "degree": detect_degree(text),
                    "funded": bool(FUNDED_RX.search(text)) and not UNFUNDED_RX.search(text),
                    "funding_text": "", "duration_years": "",
                    "deadline": str(parse_date(dl.group(1)) or "") if dl else "",
                    "start_text": "", "source_name": f["source"], "url": e.get("link", ""),
                    "verified": False,
                })
                n += 1
            status[f["source"]] = f"ok ({n})"
        except Exception as ex:  # noqa: BLE001
            status[f["source"]] = f"failed: {ex}"[:160]
    return items, status


def from_sheet(http: Http, csv_url: str) -> list[dict]:
    text = http.get_text(csv_url)
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("title") or not r.get("url"):
            continue
        r = {k.strip(): (v or "").strip() for k, v in r.items()}
        r["id"] = r.get("id") or slug(r.get("university", ""), r["title"])
        r["funded"] = r.get("funded", "").lower() in ("true", "yes", "1", "y")
        r["verified"] = r.get("verified", "").lower() in ("true", "yes", "1", "y")
        r["subject_area"] = r.get("subject_area") or classify(r["title"])
        r["degree"] = r.get("degree") or detect_degree(r["title"])
        r["source_name"] = r.get("source_name") or "Curated sheet"
        rows.append(r)
    return rows
