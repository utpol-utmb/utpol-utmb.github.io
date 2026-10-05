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
NSF_FIELDS = ("id,title,piFirstName,piLastName,piEmail,awardeeName,awardeeCity,awardeeStateCode,awardeeCountryCode,"
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
            "pi_email": (a.get("piEmail") or "").strip().lower() if "@" in (a.get("piEmail") or "") else "",
            "department": "",
        })
    return recs


# ---------- NIH RePORTER ----------------------------------------------------------
NIH_URL = "https://api.reporter.nih.gov/v2/projects/search"
NIH_ACTIVITY = ["R01", "R21", "R03", "R34", "R35", "R37", "U01", "U19", "P01", "P30", "P50", "T32", "T35", "D43", "R25", "K12", "KL2", "TL1"]
NIH_TRAINING = {"T32", "T35", "D43", "R25", "K12", "KL2", "TL1"}


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
                                   "ActivityCode", "AgencyIcAdmin", "ProjectDetailUrl", "PrefTerms"],
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
                "terms": (r.get("pref_terms") or "")[:600],
                "department": (org.get("dept_type") or "").title() if org.get("dept_type") not in (None, "", "NONE", "OTHER") else "",
                "pi_email": "",
                "kind": "training" if code in NIH_TRAINING else "research",
                "url": r.get("project_detail_url") or f"https://reporter.nih.gov/project-details/{r.get('appl_id')}",
            })
    return recs


# ---------- UKRI Gateway to Research ----------------------------------------------
GTR_SEARCH = "https://gtr.ukri.org/api/search/project"


def ukri_fetch(http: Http, keywords: list[str], lookback_years: int, pages: int = 4) -> list[dict]:
    """The search API returns 25 projects a page with PIs, supervisors and lead organisation inline."""
    out: dict[str, dict] = {}
    for kw in keywords:
        for page in range(1, pages + 1):
            if http.deadline and __import__('time').time() > http.deadline:
                return list(out.values())
            try:
                data = http.get_json(GTR_SEARCH, params={"term": kw, "page": page, "fetchSize": 25},
                                     headers={"Accept": "application/json"})
            except RuntimeError:
                break
            rows = (data.get("facetedSearchResultBean") or data).get("results", [])
            for r in rows:
                comp = r.get("projectComposition") or {}
                proj = comp.get("project") or {}
                if proj.get("id"):
                    out[proj["id"]] = comp
            if len(rows) < 25:
                break
    return list(out.values())


def ukri_normalize(comps: list[dict]) -> list[dict]:
    recs = []
    for comp in comps:
        proj = comp.get("project") or {}
        fund = proj.get("fund") or {}
        end = dt.date.fromtimestamp(fund["end"] / 1000) if fund.get("end") else None
        if end and end < TODAY:
            continue
        start = dt.date.fromtimestamp(fund["start"] / 1000).isoformat() if fund.get("start") else ""
        org = (comp.get("leadResearchOrganisation") or {}).get("name", "")
        cat = proj.get("grantCategory", "")
        funder = (fund.get("funder") or {}).get("name", "")
        people = (comp.get("principalInvestigators") or []) + (comp.get("supervisors") or [])
        for pi in people[:2]:
            name = pi.get("fullName") or f"{pi.get('firstName', '')} {pi.get('surname', '')}".strip()
            if not name:
                continue
            recs.append({
                "agency": f"UKRI {funder} (UK)".replace("  ", " "), "number": proj.get("grantReference", ""),
                "title": proj.get("title", ""), "pi_name": name, "institution": org,
                "city": "", "state": "", "country": "United Kingdom",
                "amount": float(fund.get("valuePounds") or 0), "currency": "GBP",
                "start": start, "end": str(end or ""), "program": cat,
                "terms": (proj.get("abstractText") or "")[:400],
                "kind": "training" if "studentship" in cat.lower() or "training" in cat.lower() else "research",
                "url": f"https://gtr.ukri.org/projects?ref={proj.get('grantReference', '')}",
            })
    return recs


# ---------- Australian Research Council (NCGP data portal) -------------------------
ARC_URL = "https://dataportal.arc.gov.au/NCGP/API/grants"
ARC_TRAINING = ("Training Centre", "Industrial Transformation Training")


def arc_fetch(http: Http, keywords: list[str], lookback_years: int, page_size: int = 100, max_pages: int = 120) -> list[dict]:
    """Grants are listed newest scheme round first; stop once rounds are older than the lookback."""
    oldest = TODAY.year - lookback_years
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        if http.deadline and __import__('time').time() > http.deadline:
            break
        data = http.get_json(ARC_URL, params={"page[size]": page_size, "page[number]": page})
        rows = data.get("data", [])
        if not rows:
            break
        out += rows
        years = [(r.get("attributes") or {}).get("funding-commencement-year") or 0 for r in rows]
        if years and max(years) < oldest:
            break
    return out


def arc_normalize(rows: list[dict]) -> list[dict]:
    recs = []
    oldest = TODAY.year - 4
    for r in rows:
        a = r.get("attributes") or {}
        year = a.get("funding-commencement-year") or 0
        if year < oldest:
            continue
        end = parse_date(a.get("anticipated-end-date") or "")
        if end and end < TODAY:
            continue
        status = (a.get("grant-status") or "").lower()
        if status and any(s in status for s in ("closed", "completed", "terminated", "withdrawn")):
            continue
        name = (a.get("lead-investigator") or "").strip()
        if not name:
            continue
        scheme = a.get("scheme-name") or ""
        summary = a.get("grant-summary") or ""
        recs.append({
            "agency": "ARC (Australia)", "number": a.get("code") or r.get("id", ""),
            "title": summary.split(" . ")[0][:200] if " . " in summary[:220] else summary[:160],
            "pi_name": name, "institution": a.get("current-admin-organisation") or a.get("announcement-admin-organisation") or "",
            "city": "", "state": "", "country": "Australia",
            "amount": float(a.get("current-funding-amount") or a.get("announced-funding-amount") or 0), "currency": "AUD",
            "start": f"{year}-01-01" if year else "", "end": str(end or ""), "program": scheme,
            "terms": f"{a.get('primary-field-of-research', '')} {summary[:500]}",
            "kind": "training" if any(t in scheme for t in ARC_TRAINING) else "research",
            "url": f"https://dataportal.arc.gov.au/NCGP/Web/Grant/Grant/{a.get('code') or r.get('id', '')}",
        })
    return recs
