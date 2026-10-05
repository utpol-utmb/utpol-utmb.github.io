"""EURAXESS (European Commission) job adverts for First Stage Researchers (R1) = PhD candidates.

Reads the public search results filtered to "First Stage Researcher (R1)", newest first, and
opens each new advert once to read its deadline, organisation, field and start date. Adverts
already seen are kept in pipeline/cache/euraxess.json, so a normal day opens only new ones.

EU-owned content is reusable under the Commission's reuse policy (CC BY 4.0) with credit;
we keep a short factual summary and always link to the original advert.
robots.txt is honoured by the Http helper. Requests are paced (one every ~1.5 s).
"""
from __future__ import annotations

import datetime as dt
import html as htmllib
import json
import pathlib
import re
import time

from common import TODAY, Http, country_name

BASE = "https://euraxess.ec.europa.eu"
SEARCH = BASE + "/jobs/search"
R1_FACET = "job_research_profile:447"   # "First Stage Researcher (R1)"
CACHE = pathlib.Path(__file__).resolve().parent.parent / "cache" / "euraxess.json"
PHD_RX = re.compile(r"\b(phd|ph\.d|doctoral|doctorate|dphil|thèse|these|promotion|doktorand|dottorato|doctorado)\b", re.I)


def _text(s: str) -> str:
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_search(page_html: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r'href="/jobs/(\d+)"', page_html)))


def parse_detail(job_id: str, page: str) -> dict:
    fields: dict[str, str] = {}
    for term, val in re.findall(r'<dt class="ecl-description-list__term">(.*?)</dt>\s*<dd class="ecl-description-list__definition">(.*?)</dd>', page, flags=re.S):
        key = _text(term)
        if key in fields:
            continue
        m = re.search(r'<time datetime="([0-9-]{10})', val)
        fields[key] = m.group(1) if m else _text(val)
    tm = re.search(r'<h1[^>]*>(.*?)</h1>', page, flags=re.S)
    title = _text(tm.group(1)) if tm else ""
    full = _text(page)
    i = full.rfind("Offer Description")
    j = min([k for k in (full.find("Where to apply", i + 1), full.find("Requirements", i + 1)) if k > i] or [i + 1600])
    desc = full[i + len("Offer Description"):j].strip()[:1500] if i >= 0 else ""
    return {
        "eid": job_id, "title": title,
        "organisation": fields.get("Organisation/Company", ""), "department": fields.get("Department", ""),
        "field": fields.get("Research Field", ""), "profile": fields.get("Researcher Profile", ""),
        "deadline": fields.get("Application Deadline", "")[:10] if re.match(r"\d{4}-", fields.get("Application Deadline", "")) else "",
        "country": country_name(fields.get("Country", "")), "start": fields.get("Offer Starting Date", ""),
        "eu_funded": fields.get("Is the job funded through the EU Research Framework Programme?", ""),
        "description": desc, "checked": TODAY.isoformat(),
    }


def fetch(http: Http, max_pages: int = 6, max_details: int = 120, pause: float = 3.0) -> tuple[list[dict], dict]:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    seen_ids: list[str] = []
    for page in range(max_pages):
        if http.deadline and time.time() > http.deadline:
            break
        params = {"f[0]": R1_FACET}
        if page:
            params["page"] = page
        try:
            ids = parse_search(http.get_text(SEARCH, params=params))
        except RuntimeError:
            break
        if not ids:
            break
        seen_ids += ids
        time.sleep(pause)
    opened = 0
    for jid in dict.fromkeys(seen_ids):
        if jid in cache or opened >= max_details:
            continue
        if http.deadline and time.time() > http.deadline:
            break
        try:
            cache[jid] = parse_detail(jid, http.get_text(f"{BASE}/jobs/{jid}"))
            opened += 1
        except RuntimeError:
            continue
        time.sleep(pause)
    # forget adverts whose deadline passed more than 30 days ago
    cutoff = (TODAY - dt.timedelta(days=30)).isoformat()
    cache = {k: v for k, v in cache.items() if not v.get("deadline") or v["deadline"] >= cutoff}
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, separators=(",", ":"), ensure_ascii=False, sort_keys=True))
    rows = [v for v in cache.values() if (not v.get("deadline") or v["deadline"] >= TODAY.isoformat())]
    return rows, {"listed": len(seen_ids), "opened": opened, "cached": len(cache)}


def to_positions(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        text = f"{r['title']} {r['description']}"
        if "R1" not in r.get("profile", "") and not PHD_RX.search(text):
            continue
        if re.search(r"post-?doc|postdoctoral", r["title"], re.I) and not PHD_RX.search(r["title"]):
            continue
        funded_hint = "EU-funded (Horizon Europe / MSCA)" if "Horizon" in r.get("eu_funded", "") or "Marie" in r.get("eu_funded", "") else ""
        out.append({
            "id": "euraxess-" + r["eid"], "title": r["title"], "supervisor": "",
            "university": r["organisation"], "department": r.get("department", ""), "city": "", "country": r["country"],
            "degree": "PhD", "funded": True,
            "funding_text": funded_hint or "Employment contract (EURAXESS researcher post); see advert for salary",
            "duration_years": "", "deadline": r["deadline"], "start_text": r.get("start", ""),
            "source_name": "EURAXESS", "url": f"{BASE}/jobs/{r['eid']}", "verified": False,
            "classify_text": f"{r['title']} {r['title']} {r.get('field', '')} {r['description'][:600]}",
            "description": r["description"][:400], "source_checked": r.get("checked", ""),
        })
    return out
