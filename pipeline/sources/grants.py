"""Funded-grant collectors: NSF, NIH RePORTER, UKRI Gateway to Research.

Each returns a list of *grant records* (one per PI per grant):
  {agency, number, title, pi_name, institution, city, state, country, amount, currency,
   start, end, program, kind, url}
kind is "training" (the grant funds graduate students directly) or "research".
"""
from __future__ import annotations

import datetime as dt

from common import TODAY, US_STATES, Http, parse_date

# ---------- NSF ----------------------------------------------------------------
NSF_URL = "https://api.nsf.gov/services/v1/awards.json"
NSF_FIELDS = ("id,title,piFirstName,piLastName,awardeeName,awardeeCity,awardeeStateCode,awardeeCountryCode,"
              "fundsObligatedAmt,startDate,expDate,fundProgramName,agency")
NSF_SKIP = ("REU Site", "Conference:", "Workshop:", "Travel:", "S-STEM", "Planning:")
NSF_TRAINING = ("Graduate Fellowship", "NRT:", "Research Traineeship", "EGFP", "GRFP")


def nsf_fetch(http: Http, keywords: list[str], lookback_years: int) -> list[dict]:
    since = (TODAY - dt.timedelta(days=365 * lookback_years)).strftime("%m/%d/%Y")
    out: dict[str, dict] = {}
    for kw in keywords:
        offset = 1
        while offset <= 100:  # cap per keyword to stay polite
            if http.deadline and __import__('time').time() > http.deadline:
                return list(out.values())
            try:
                data = http.get_json(NSF_URL, params={"keyword": kw, "printFields": NSF_FIELDS,
                                                      "dateStart": since, "rpp": 25, "offset": offset})
            except RuntimeError:
                break
            awards = data.get("response", {}).get("award", [])
            for a in awards:
                out[a["id"]] = a
            if len(awards) < 25:
                break
            offset += 25
    return list(out.values())


def nsf_normalize(awards: list[dict]) -> list[dict]:
    recs = []
    for a in awards:
        title = a.get("title", "")
        if any(s.lower() in title.lower() for s in NSF_SKIP):
            continue
        end = parse_date(a.get("expDate"))
        if end and end < TODAY:
            continue
        state = a.get("awardeeStateCode", "")
        is_training = any(s.lower() in (title + a.get("fundProgramName", "")).lower() for s in NSF_TRAINING)
        recs.append({
            "agency": "NSF (USA)", "number": a["id"], "title": title,
            "pi_name": f"{a.get('piFirstName', '')} {a.get('piLastName', '')}".strip(),
            "institution": a.get("awardeeName", ""), "city": a.get("awardeeCity", ""), "state": state,
            "country": "United States" if (state in US_STATES or a.get("awardeeCountryCode") == "US") else "",
            "amount": float(a.get("fundsObligatedAmt") or 0), "currency": "USD",
            "start": str(parse_date(a.get("startDate")) or ""), "end": str(end or ""),
            "program": a.get("fundProgramName", ""),
            "kind": "training" if is_training else "research",
            "url": f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={a['id']}",
        })
    return recs


# ---------- NIH RePORTER ----------------------------------------------------------
NIH_URL = "https://api.reporter.nih.gov/v2/projects/search"
NIH_ACTIVITY = ["R01", "R21", "R03", "R34", "U01", "P01", "K99", "T32", "T35", "F31", "D43", "R25"]
NIH_TRAINING = {"T32", "T35", "D43", "R25", "F31"}


def nih_fetch(http: Http, keywords: list[str], lookback_years: int) -> list[dict]:
    fy = TODAY.year + (1 if TODAY.month >= 10 else 0)
    years = list(range(fy - lookback_years + 1, fy + 1))
    out: dict[str, dict] = {}
    for kw in keywords:
        offset = 0
        while offset < 300:
            if http.deadline and __import__('time').time() > http.deadline:
                return list(out.values())
            payload = {
                "criteria": {
                    "fiscal_years": years,
                    "activity_codes": NIH_ACTIVITY,
                    "project_end_date": {"from_date": TODAY.isoformat(), "to_date": "2040-12-31"},
                    "advanced_text_search": {"operator": "and", "search_field": "projecttitle,terms",
                                             "search_text": kw},
                },
                "include_fields": ["ApplId", "ProjectNum", "ProjectTitle", "PrincipalInvestigators",
                                   "Organization", "AwardAmount", "ProjectStartDate", "ProjectEndDate",
                                   "ActivityCode", "AgencyIcAdmin", "ProjectDetailUrl"],
                "offset": offset, "limit": 100,
            }
            try:
                data = http.post_json(NIH_URL, payload)
            except RuntimeError:
                break
            rows = data.get("results", [])
            for r in rows:
                out[str(r.get("appl_id"))] = r
            if len(rows) < 100:
                break
            offset += 100
    return list(out.values())


def nih_normalize(rows: list[dict]) -> list[dict]:
    recs = []
    for r in rows:
        org = r.get("organization") or {}
        pis = r.get("principal_investigators") or []
        code = r.get("activity_code", "")
        for pi in pis[:3]:
            name = pi.get("full_name") or f"{pi.get('first_name', '')} {pi.get('last_name', '')}"
            recs.append({
                "agency": "NIH (USA)", "number": r.get("project_num", ""), "title": r.get("project_title", ""),
                "pi_name": " ".join(name.split()).title(),
                "institution": (org.get("org_name") or "").title(),
                "city": (org.get("org_city") or "").title(), "state": org.get("org_state", ""),
                "country": (org.get("org_country") or "United States").title().replace("United States", "United States"),
                "amount": float(r.get("award_amount") or 0), "currency": "USD",
                "start": (r.get("project_start_date") or "")[:10], "end": (r.get("project_end_date") or "")[:10],
                "program": f"{code} ({(r.get('agency_ic_admin') or {}).get('abbreviation', '')})",
                "kind": "training" if code in NIH_TRAINING else "research",
                "url": r.get("project_detail_url") or f"https://reporter.nih.gov/project-details/{r.get('appl_id')}",
            })
    return recs


# ---------- UKRI Gateway to Research ----------------------------------------------
GTR = "https://gtr.ukri.org/api"
GTR_HEADERS = {"Accept": "application/vnd.rcuk.gtr.json-v7"}


def ukri_fetch(http: Http, keywords: list[str], lookback_years: int, per_kw: int = 15) -> list[dict]:
    """Returns projects with their PI person and lead organisation resolved."""
    out: dict[str, dict] = {}
    for kw in keywords:
        if http.deadline and __import__('time').time() > http.deadline:
            break
        try:
            data = http.get_json(f"{GTR}/projects", params={"q": kw, "s": per_kw, "p": 1}, headers=GTR_HEADERS)
        except RuntimeError:
            continue
        for p in data.get("project", []):
            if p.get("status") != "Active" or p["id"] in out:
                continue
            links = {l.get("rel"): l.get("href") for l in (p.get("links") or {}).get("link", [])}
            try:
                if links.get("PI_PER"):
                    per = http.get_json(links["PI_PER"], headers=GTR_HEADERS)
                    p["_pi"] = f"{per.get('firstName', '')} {per.get('surname', '')}".strip()
                if links.get("LEAD_ORG"):
                    org = http.get_json(links["LEAD_ORG"], headers=GTR_HEADERS)
                    p["_org"] = org.get("name", "")
                if links.get("FUND"):
                    fund = http.get_json(links["FUND"], headers=GTR_HEADERS)
                    p["_amount"] = (fund.get("valuePounds") or {}).get("amount")
                    p["_start"] = fund.get("start")
                    p["_end"] = fund.get("end")
            except RuntimeError:
                if http.deadline and __import__('time').time() > http.deadline:
                    return list(out.values())
                continue
            out[p["id"]] = p
    return list(out.values())


def ukri_normalize(projects: list[dict]) -> list[dict]:
    recs = []
    for p in projects:
        if not p.get("_pi"):
            continue
        end = parse_date(str(p.get("_end") or "")[:10]) if p.get("_end") else None
        if isinstance(p.get("_end"), (int, float)):
            end = dt.date.fromtimestamp(p["_end"] / 1000)
        if end and end < TODAY:
            continue
        start = p.get("_start")
        if isinstance(start, (int, float)):
            start = dt.date.fromtimestamp(start / 1000).isoformat()
        cat = p.get("grantCategory", "")
        recs.append({
            "agency": f"UKRI {p.get('leadFunder', '')}".strip() + " (UK)", "number": p.get("id", ""),
            "title": p.get("title", ""), "pi_name": p["_pi"], "institution": p.get("_org", ""),
            "city": "", "state": "", "country": "United Kingdom",
            "amount": float(p.get("_amount") or 0), "currency": "GBP",
            "start": str(start or "")[:10], "end": str(end or ""), "program": cat,
            "kind": "training" if "studentship" in cat.lower() or "training" in cat.lower() else "research",
            "url": f"https://gtr.ukri.org/projects?ref={p.get('identifiers', {}).get('identifier', [{}])[0].get('value', p.get('id'))}",
        })
    return recs
