"""Enrich supervisors with OpenAlex (open scholarly data, CC0).

For each supervisor (looked up once every `refresh_days`, cached in pipeline/cache/openalex.json):
  * metrics      works, citations, h-index, ORCID iD, OpenAlex profile
  * topics       display names of their main research topics
  * oa_subfields [{subfield, count}] from their topics -> used by the Field > Subfield tree
  * papers       3 most recent works (title, year, link)
  * inst         official institution website (homepage) and ROR id, cached per institution

Only api.openalex.org is called. Nothing personal (emails, phone numbers) is stored.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import time

from common import TODAY, Http

API = "https://api.openalex.org"
CACHE = pathlib.Path(__file__).resolve().parent.parent / "cache" / "openalex.json"
INST_CACHE = pathlib.Path(__file__).resolve().parent.parent / "cache" / "openalex_institutions.json"
VERSION = 2  # bump to force a refresh of every cached entry
AUTHOR_FIELDS = "id,display_name,orcid,works_count,cited_by_count,summary_stats,last_known_institutions,affiliations,topics"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _inst_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    for w in ("university", "of", "the", "at", "college", "institute", "researchfoundation", "inc", "school"):
        a, b = a.replace(w, ""), b.replace(w, "")
    return bool(a) and bool(b) and (a[:10] in b or b[:10] in a)


def _load(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def apply_cached(m: dict, hit: dict) -> None:
    if hit.get("metrics"):
        m["metrics"] = hit["metrics"]
        m["topics"] = hit.get("topics", [])
        m["oa_subfields"] = hit.get("oa_subfields", [])
        m["papers"] = hit.get("papers", [])
    if hit.get("inst"):
        m["inst_site"] = hit["inst"]


def _institution(http: Http, inst_id: str, cache: dict, contact: str) -> dict:
    key = inst_id.rsplit("/", 1)[-1]
    if key in cache:
        return cache[key]
    try:
        d = http.get_json(f"{API}/institutions/{key}", params={"select": "homepage_url,ror,display_name,country_code", "mailto": contact})
        cache[key] = {"homepage": d.get("homepage_url") or "", "ror": d.get("ror") or "", "name": d.get("display_name") or "",
                      "country_code": d.get("country_code") or ""}
    except RuntimeError:
        cache[key] = {}
    return cache[key]


def enrich(http: Http, mentors: list[dict], contact: str, max_lookups: int = 2500, refresh_days: int = 45) -> dict:
    cache, icache = _load(CACHE), _load(INST_CACHE)
    cutoff = (TODAY - dt.timedelta(days=refresh_days)).isoformat()
    stats = {"lookups": 0, "matched": 0, "stopped_early": False}
    # people who are recruiting now get looked up first
    order = sorted(mentors, key=lambda m: ({"open_position": 0, "training_grant": 1}.get(m["signal"], 2), m["id"]))
    for m in order:
        hit = cache.get(m["id"])
        if hit and hit.get("checked", "") >= cutoff and hit.get("v") == VERSION:
            apply_cached(m, hit)
            continue
        if stats["lookups"] >= max_lookups or (http.deadline and time.time() > http.deadline):
            stats["stopped_early"] = True
            if hit:
                apply_cached(m, hit)  # older data is better than none
            continue
        name = re.sub(r"\b(Dr|Prof|Professor|Assoc|Asst)\.?\s*", "", m["name"]).strip()
        try:
            data = http.get_json(f"{API}/authors", params={"search": name, "per-page": 10, "select": AUTHOR_FIELDS, "mailto": contact})
        except RuntimeError:
            continue
        stats["lookups"] += 1
        match = None
        for a in data.get("results", []):
            insts = [i.get("display_name", "") for i in (a.get("last_known_institutions") or [])]
            insts += [aff.get("institution", {}).get("display_name", "") for aff in (a.get("affiliations") or [])[:5]]
            if any(_inst_match(i, m["institution"]) for i in insts):
                match = a
                break
        entry = {"checked": TODAY.isoformat(), "v": VERSION}
        if match:
            stats["matched"] += 1
            st = match.get("summary_stats") or {}
            entry["metrics"] = {"works": match.get("works_count"), "citations": match.get("cited_by_count"),
                                "h_index": st.get("h_index"), "orcid": match.get("orcid") or "", "openalex": match.get("id", "")}
            topics = match.get("topics") or []
            entry["topics"] = [t.get("display_name") for t in topics[:5]]
            entry["oa_subfields"] = []
            for t in topics[:15]:
                sid = ((t.get("subfield") or {}).get("id") or "").rsplit("/", 1)[-1]
                if sid.isdigit():
                    entry["oa_subfields"].append({"subfield": int(sid), "count": t.get("count") or 1})
            try:
                w = http.get_json(f"{API}/works", params={
                    "filter": f"author.id:{match['id'].rsplit('/', 1)[-1]},type:article|review|preprint",
                    "sort": "publication_date:desc", "per-page": 3, "select": "id,title,publication_year,doi", "mailto": contact})
                entry["papers"] = [{"title": (x.get("title") or "")[:220], "year": x.get("publication_year"),
                                    "url": x.get("doi") or x.get("id")} for x in w.get("results", []) if x.get("title")]
            except RuntimeError:
                entry["papers"] = []
            lki = (match.get("last_known_institutions") or [{}])[0]
            if lki.get("id"):
                inst = _institution(http, lki["id"], icache, contact)
                if inst.get("homepage"):
                    entry["inst"] = {"homepage": inst["homepage"], "ror": inst.get("ror", "")}
        cache[m["id"]] = entry
        apply_cached(m, entry)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, separators=(",", ":"), sort_keys=True))
    INST_CACHE.write_text(json.dumps(icache, separators=(",", ":"), sort_keys=True))
    return stats
