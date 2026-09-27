"""Enrich mentors with OpenAlex: publications, citations, h-index, topics, ORCID.

Results are cached in pipeline/cache/openalex.json so each person is looked up
once every 30 days, keeping the daily run fast and polite.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

from common import TODAY, Http

API = "https://api.openalex.org/authors"
CACHE = pathlib.Path(__file__).resolve().parent.parent / "cache" / "openalex.json"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def _inst_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    stop = ("university", "of", "the", "at", "college", "institute", "researchfoundation", "inc")
    for w in stop:
        a, b = a.replace(w, ""), b.replace(w, "")
    return a[:10] in b or b[:10] in a


def enrich(http: Http, mentors: list[dict], contact: str, max_lookups: int = 400) -> int:
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    fresh_cutoff = (TODAY - dt.timedelta(days=30)).isoformat()
    lookups = 0
    for m in mentors:
        key = m["id"]
        hit = cache.get(key)
        if hit and hit.get("checked", "") >= fresh_cutoff:
            if hit.get("metrics"):
                m["metrics"], m["topics"] = hit["metrics"], hit.get("topics", m.get("topics", []))
            continue
        if lookups >= max_lookups:
            continue
        name = re.sub(r"\b(Dr|Prof|Professor|Assoc|Asst)\.?\s*", "", m["name"]).strip()
        try:
            data = http.get_json(API, params={"search": name, "per-page": 10, "mailto": contact})
        except RuntimeError:
            continue
        lookups += 1
        match = None
        for a in data.get("results", []):
            insts = [i.get("display_name", "") for i in (a.get("last_known_institutions") or [])]
            insts += [aff.get("institution", {}).get("display_name", "") for aff in (a.get("affiliations") or [])[:5]]
            if any(_inst_match(i, m["institution"]) for i in insts):
                match = a
                break
        entry = {"checked": TODAY.isoformat()}
        if match:
            stats = match.get("summary_stats") or {}
            entry["metrics"] = {
                "works": match.get("works_count"), "citations": match.get("cited_by_count"),
                "h_index": stats.get("h_index"), "orcid": match.get("orcid") or "",
                "openalex": match.get("id", ""),
            }
            entry["topics"] = [t.get("display_name") for t in (match.get("topics") or [])[:5]]
            m["metrics"], m["topics"] = entry["metrics"], entry["topics"]
        cache[key] = entry
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))
    return lookups
