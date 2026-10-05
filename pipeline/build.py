"""Build the app's data files.

    python pipeline/build.py            # live run (used by the daily GitHub Action)
    python pipeline/build.py --offline  # uses saved sample data, no internet needed

Writes site/data/positions.json, mentors.json, funding.json and meta.json.
If a source fails, the last good copy of that source is reused, so one broken
website never empties the app.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "pipeline" / "sources"))

from common import TODAY, Http, classify, intake_year, parse_date, person_key, region_for, slug  # noqa: E402
import grants as G  # noqa: E402
import positions as P  # noqa: E402
import openalex as OA  # noqa: E402

OUT = ROOT / "site" / "data"
CACHE = ROOT / "pipeline" / "cache"
FIX = ROOT / "pipeline" / "fixtures"
CURATED = ROOT / "data" / "curated"


def load_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- money parsing
CUR = {"£": "GBP", "€": "EUR", "$": "USD", "USD": "USD", "GBP": "GBP", "EUR": "EUR", "NOK": "NOK",
       "AUD": "AUD", "CAD": "CAD", "CHF": "CHF", "SEK": "SEK", "DKK": "DKK", "TRY": "TRY", "HUF": "HUF", "¥": "JPY"}
MONEY_RX = re.compile(r"(AUD|CAD|USD|GBP|EUR|NOK|CHF|SEK|DKK|TRY|HUF|[£€$¥])\s?([\d][\d,]*(?:\.\d+)?)")


def annual_usd(text: str, rates: dict) -> float | None:
    m = MONEY_RX.search(text or "")
    if not m:
        return None
    cur = CUR.get(m.group(1))
    amount = float(m.group(2).replace(",", ""))
    if cur not in rates:
        return None
    window = text[m.end(): m.end() + 30].lower()
    if "month" in window or "/month" in window:
        amount *= 12
    if amount < 3000:  # probably not an annual figure
        return None
    return round(amount * rates[cur])


def deadline_status(deadline: str) -> tuple[str, int | None]:
    if not deadline or deadline.lower().startswith("open"):
        return ("open", None)
    d = parse_date(deadline)
    if not d:
        return ("check", None)
    days = (d - TODAY).days
    if days < 0:
        return ("closed", days)
    return ("soon" if days <= 21 else "open", days)


# ---------------------------------------------------------------- stages
def collect_grants(cfg, http, offline, status) -> list[dict]:
    kws, yrs = cfg["search_keywords"], cfg["grant_lookback_years"]
    recs: list[dict] = []
    plan = [("nsf", G.nsf_fetch, G.nsf_normalize), ("nih", G.nih_fetch, G.nih_normalize),
            ("ukri", G.ukri_fetch, G.ukri_normalize)]
    for name, fetch, norm in plan:
        last_good = CACHE / f"grants_{name}.json"
        if not cfg["sources"].get(name):
            status[name] = "off"
            continue
        try:
            if offline:
                fx = FIX / f"{name}_sample.json"
                if not fx.exists():
                    raise FileNotFoundError("no offline sample")
                raw = load_json(fx, {})
                raw = raw.get("response", {}).get("award", raw) if name == "nsf" else raw
            else:
                http.budget(cfg.get("minutes_per_source", 8))
                try:
                    raw = fetch(http, kws, yrs)
                finally:
                    http.budget(None)
            got = norm(raw)
            if not got:
                raise RuntimeError("returned 0 records")
            if not offline:  # sample data must never replace the last good live copy
                save_json(last_good, got)
            status[name] = f"ok ({len(got)} grants)"
        except Exception as ex:  # noqa: BLE001
            got = load_json(last_good, [])
            status[name] = f"used last good copy ({len(got)}) — {str(ex)[:120]}"
        recs.extend(got)
    return recs


def collect_positions(cfg, http, offline, status, rates, first_seen) -> list[dict]:
    rows = load_json(CURATED / "positions.json", [])
    status["curated_positions"] = f"ok ({len(rows)})"
    if not offline and cfg["sources"].get("rss_feeds"):
        items, st = P.from_rss(http, cfg.get("rss_feeds", []))
        rows += items
        status.update({f"rss: {k}": v for k, v in st.items()})
    if not offline and cfg["sources"].get("sheet") and cfg.get("sheet_csv_url"):
        try:
            sheet = P.from_sheet(http, cfg["sheet_csv_url"])
            rows += sheet
            status["sheet"] = f"ok ({len(sheet)})"
        except Exception as ex:  # noqa: BLE001
            status["sheet"] = f"failed: {ex}"[:160]

    out, seen_urls = [], set()
    for r in rows:
        url = (r.get("url") or "").split("?utm")[0]
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        r["id"] = r.get("id") or slug(r.get("university", ""), r.get("title", ""))
        first = first_seen.setdefault("p:" + r["id"], TODAY.isoformat())
        st, days = deadline_status(str(r.get("deadline", "")))
        if st == "closed":
            continue
        if str(r.get("deadline", "")).lower().startswith("open"):
            if (TODAY - dt.date.fromisoformat(first)).days > cfg.get("open_until_filled_days", 120):
                continue
        r["deadline_status"], r["days_left"] = st, days
        r["region"] = region_for(r.get("country", ""))
        r["subject_area"] = r.get("subject_area") or classify(r.get("title", ""))
        r["intake_year"] = intake_year(r.get("start_text", ""))
        r["annual_usd_approx"] = annual_usd(r.get("funding_text", ""), rates)
        r["first_seen"] = first
        out.append(r)
    out.sort(key=lambda r: (r["days_left"] is None, r["days_left"] or 0))
    return out


TITLE_RX = re.compile(r"^((?:Assoc\.?|Asst\.?|Associate|Assistant)\s+)?(?:Prof(?:essor)?\.?|Dr\.?)(\s+(?:Dr\.?|Ir))*\s+", re.I)


def clean_name(name: str) -> str:
    return TITLE_RX.sub("", name.strip()).strip()


def split_people(s: str) -> list[tuple[str, str]]:
    """'Dr A; Prof B (Cardiff University)' -> [('A',''), ('B','Cardiff University')]"""
    out = []
    for part in re.split(r";", s or ""):
        inst = ""
        m = re.search(r"\(([^)]*)\)", part)
        if m and re.search(r"universit|institut|college|school|hospital", m.group(1), re.I):
            inst = m.group(1).strip()
        part = re.sub(r"\(.*?\)", "", part)
        part = re.sub(r"\b(main|co-supervisors?)\b:?", "", part, flags=re.I).strip(" ,.")
        if len(part) > 4:
            out.append((clean_name(part), inst))
    return out


SIGNAL_RANK = {"open_position": 3, "training_grant": 2, "research_grant": 1}
SIGNAL_LABEL = {"open_position": "Advertising a position now",
                "training_grant": "Holds a grant that funds graduate students",
                "research_grant": "Active research grant — may take students"}


def build_mentors(grants: list[dict], positions: list[dict], first_seen: dict) -> list[dict]:
    people: dict[str, dict] = {}

    def get(name, inst, country, city=""):
        k = person_key(name, inst)
        if k not in people:
            people[k] = {"id": slug(name, inst), "name": name, "institution": inst, "city": city,
                         "country": country, "region": region_for(country), "subject_area": "",
                         "topics": [], "signal": "research_grant", "grants": [], "positions": [],
                         "metrics": None, "sources": set()}
        return people[k]

    for p in positions:
        for name, other_inst in split_people(p.get("supervisor", "")):
            if other_inst:
                m = get(name, other_inst, p.get("country", ""))
            else:
                m = get(name, p.get("university", ""), p.get("country", ""), p.get("city", ""))
            m["positions"].append(p["id"])
            m["signal"] = "open_position"
            m["subject_area"] = m["subject_area"] or p["subject_area"]
            m["sources"].add(p.get("source_name", ""))
    for g in grants:
        m = get(g["pi_name"], g["institution"], g["country"], g.get("city", ""))
        m["grants"].append({k: g[k] for k in ("agency", "number", "title", "amount", "currency", "start",
                                               "end", "program", "kind", "url")})
        m["_terms"] = (m.get("_terms", "") + " " + g.get("terms", ""))[:2000]
        sig = "training_grant" if g["kind"] == "training" else "research_grant"
        if SIGNAL_RANK[sig] > SIGNAL_RANK[m["signal"]]:
            m["signal"] = sig
        m["sources"].add(g["agency"])

    out = []
    for m in people.values():
        if not m["subject_area"]:
            m["subject_area"] = classify(" ".join(g["title"] + " " + g["program"] for g in m["grants"]) + " " + m.pop("_terms", ""))
        m.pop("_terms", None)
        m["grants"].sort(key=lambda g: (g["kind"] != "training", -g["amount"]))
        m["grants"] = m["grants"][:6]
        m["signal_label"] = SIGNAL_LABEL[m["signal"]]
        m["sources"] = sorted(s for s in m["sources"] if s)
        m["total_active_funding_usd"] = round(sum(g["amount"] for g in m["grants"] if g["currency"] == "USD"))
        m["first_seen"] = first_seen.setdefault("m:" + m["id"], TODAY.isoformat())
        out.append(m)
    out.sort(key=lambda m: (-SIGNAL_RANK[m["signal"]], m["name"].split()[-1]))
    return out


def build_funding(rates) -> list[dict]:
    rows = load_json(CURATED / "scholarships.json", [])
    for r in rows:
        st, days = deadline_status(r.get("deadline", ""))
        r["deadline_status"] = "check" if not r.get("deadline") else st
        r["days_left"] = days
        r["annual_usd_approx"] = annual_usd(r.get("stipend_text", ""), rates)
        r["intake_year"] = intake_year(r.get("intake", ""))
    return rows


def main() -> int:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", default=str(OUT), help="folder for the data files (default site/data)")
    args = ap.parse_args()
    OUT = pathlib.Path(args.out)

    cfg = yaml.safe_load((ROOT / "pipeline" / "config.yaml").read_text())
    http = Http(cfg.get("contact_email", "anonymous@example.com"))
    rates = cfg.get("usd_rates", {})
    status: dict[str, str] = {}
    first_seen = load_json(CACHE / "first_seen.json", {})
    prev_meta = load_json(OUT / "meta.json", {})

    grants = collect_grants(cfg, http, args.offline, status)
    positions = collect_positions(cfg, http, args.offline, status, rates, first_seen)
    mentors = build_mentors(grants, positions, first_seen)
    if cfg["sources"].get("openalex") and not args.offline:
        http.budget(cfg.get("openalex_minutes", 25))
        n = OA.enrich(http, mentors, cfg.get("contact_email", ""))
        http.budget(None)
        status["openalex"] = f"ok ({n} new lookups)"
    elif args.offline:
        # reuse any cached enrichment
        cache = load_json(CACHE / "openalex.json", {})
        for m in mentors:
            hit = cache.get(m["id"], {})
            if hit.get("metrics"):
                m["metrics"], m["topics"] = hit["metrics"], hit.get("topics", [])
    for m in mentors:  # OpenAlex topics can settle a subject the grant titles could not
        if m["subject_area"] == "Other" and m.get("topics"):
            m["subject_area"] = classify(" ".join(m["topics"]))
    funding = build_funding(rates)

    # Safety check: never publish a big unexpected drop.
    prev_total = (prev_meta.get("counts") or {}).get("mentors", 0) + (prev_meta.get("counts") or {}).get("positions", 0)
    new_total = len(mentors) + len(positions)
    if prev_total > 50 and new_total < prev_total * 0.4:
        print(f"ABORT: records dropped from {prev_total} to {new_total}. Keeping previous data.", file=sys.stderr)
        print(json.dumps(status, indent=1), file=sys.stderr)
        return 2

    facets = {
        "countries": sorted({r["country"] for r in positions + mentors if r.get("country")}),
        "subjects": sorted({r["subject_area"] for r in positions + mentors if r.get("subject_area")}),
        "intake_years": sorted({r["intake_year"] for r in positions if r.get("intake_year")}),
    }
    meta = {"generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "counts": {"positions": len(positions), "mentors": len(mentors), "funding": len(funding),
                       "grants": len(grants)},
            "source_status": status, "facets": facets, "offline": args.offline}

    save_json(OUT / "positions.json", positions)
    save_json(OUT / "mentors.json", mentors)
    save_json(OUT / "funding.json", funding)
    save_json(OUT / "meta.json", meta)
    if not args.offline:  # test/offline runs leave the saved first-seen dates alone
        save_json(CACHE / "first_seen.json", first_seen)
    print(json.dumps(meta["counts"]), json.dumps(status, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
