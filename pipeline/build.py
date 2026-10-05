"""Build the app's data files (run daily by the GitHub Action "Update data and publish site").

    python pipeline/build.py            # live run
    python pipeline/build.py --offline  # saved sample data, no internet (used by tests)

Writes into site/data/:
  positions.json            open PhD / Master's positions
  funding.json              scholarships
  mentors-index.json        light list of supervisors for fast search
  mentors/<00-63>.json      full supervisor details, split into 64 small files
  meta.json                 counts, subject tree, filters, source status
  health.json               per-source health report (read by the weekly check and the issue step)

Safety: a source that fails or returns nothing keeps its last good copy; if totals collapse,
nothing is published (exit code 2) and the workflow opens a GitHub issue instead.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "pipeline" / "sources"))

from common import TODAY, Http, country_name, intake_year, parse_date, person_key, region_for, slug  # noqa: E402
import grants as G  # noqa: E402
import openalex as OA  # noqa: E402
import positions as P  # noqa: E402
import taxonomy as T  # noqa: E402
from health import Health  # noqa: E402

OUT = ROOT / "site" / "data"
CACHE = ROOT / "pipeline" / "cache"
FIX = ROOT / "pipeline" / "fixtures"
CURATED = ROOT / "data" / "curated"
SHARDS = 64


def load_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: pathlib.Path, obj, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    else:
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- money and dates
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
    if "month" in window:
        amount *= 12
    if amount < 3000:
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


HOME_RX = re.compile(r"(home (fee|tuition)?\s*(students?|applicants?|status)? only|(uk|home|domestic) (students|applicants|candidates|nationals) only|"
                     r"only (open|available) to (uk|home|domestic|us|eu)|uk/eu (students|applicants)? only|home fees? only|home fee rate|"
                     r"must be (a )?(us|u\.s\.|uk|australian) (citizen|national)|(us|u\.s\.) citizens? or permanent residents?|"
                     r"citizens? (or|and) permanent residents? (of|only)|domestic students only)", re.I)
INTL_RX = re.compile(r"(international (students|applicants|candidates) (are )?(welcome|eligible|may apply)|open to (all nationalities|international)|"
                     r"regardless of (nationality|citizenship)|any nationality|all nationalities|including international|international and home|"
                     r"home and international|uk and international|overseas (students|applicants) (are )?eligible)", re.I)


def intl_status(*texts: str) -> str:
    t = " ".join(x for x in texts if x)
    if INTL_RX.search(t):
        return "international"
    if HOME_RX.search(t):
        return "home"
    return ""


def classify_item(text: str) -> dict:
    return T.from_text(text)


# ---------------------------------------------------------------- grants
def collect_grants(cfg, http, offline, health) -> list[dict]:
    yrs = cfg["grant_lookback_years"]
    extra = cfg.get("extra_search_keywords") or []
    terms_all = list(dict.fromkeys(T.search_terms() + extra))
    terms_nih = list(dict.fromkeys(T.search_terms(for_nih=True) + extra))
    plan = [("nsf", "NSF Award Search", G.nsf_fetch, G.nsf_normalize, terms_all),
            ("nih", "NIH RePORTER", G.nih_fetch, G.nih_normalize, terms_nih),
            ("ukri", "UKRI Gateway to Research", G.ukri_fetch, G.ukri_normalize, terms_all),
            ("arc", "Australian Research Council", G.arc_fetch, G.arc_normalize, [])]
    recs: list[dict] = []
    for key, label, fetch, norm, terms in plan:
        last_good = CACHE / f"grants_{key}.json"
        if not cfg["sources"].get(key):
            health.off(label)
            continue
        try:
            if offline:
                fx = FIX / f"{key}_sample.json"
                if not fx.exists():
                    health.off(label, "no offline sample")
                    got = load_json(last_good, [])
                    recs.extend(got)
                    continue
                raw = load_json(fx, {})
                raw = raw.get("response", {}).get("award", raw) if key == "nsf" else raw
            else:
                http.budget(cfg.get("minutes_per_source", 20))
                try:
                    raw = fetch(http, terms, yrs)
                finally:
                    http.budget(None)
            got = norm(raw)
            if not got:
                raise RuntimeError("returned 0 records")
            if not offline:
                save_json(last_good, got, compact=True)
            health.ok(label, len(got), f"{len(terms)} search terms" if terms else "")
        except Exception as ex:  # noqa: BLE001
            got = load_json(last_good, [])
            health.failed(label, str(ex), len(got))
        recs.extend(got)
    return recs


# ---------------------------------------------------------------- positions
def collect_positions(cfg, http, offline, health, rates, first_seen) -> list[dict]:
    hold = {s.lower() for s in (cfg.get("hold_sources") or [])}
    curated = load_json(CURATED / "positions.json", [])
    held = [r for r in curated if (r.get("source_name") or "").lower() in hold]
    rows = [dict(r, source_checked=r.get("checked") or "") for r in curated if (r.get("source_name") or "").lower() not in hold]
    health.ok("Curated positions file", len(rows), "hand-checked adverts in data/curated/positions.json")
    if held:
        health.held("Curated: " + ", ".join(sorted({r['source_name'] for r in held})), len(held),
                    "never shown: the site refused permission to republish its adverts (config.yaml hold_sources)")

    if cfg["sources"].get("euraxess") and not offline:
        import euraxess as EU
        last_good = CACHE / "positions_euraxess.json"
        try:
            http.budget(cfg.get("euraxess_minutes", 15))
            try:
                raw, st = EU.fetch(http)
            finally:
                http.budget(None)
            got = EU.to_positions(raw)
            if not got:
                raise RuntimeError(f"0 PhD adverts ({st})")
            save_json(last_good, got, compact=True)
            health.ok("EURAXESS", len(got), f"{st['listed']} listed, {st['opened']} new adverts read")
        except Exception as ex:  # noqa: BLE001
            got = load_json(last_good, [])
            health.failed("EURAXESS", str(ex), len(got))
        rows += got
    elif not cfg["sources"].get("euraxess"):
        health.off("EURAXESS")

    if cfg["sources"].get("sheet") and cfg.get("sheet_csv_url") and not offline:
        try:
            sheet = P.from_sheet(http, cfg["sheet_csv_url"])
            rows += sheet
            health.ok("Google Sheet positions", len(sheet))
        except Exception as ex:  # noqa: BLE001
            health.failed("Google Sheet positions", str(ex), 0)

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
        if str(r.get("deadline", "")).lower().startswith("open") or not r.get("deadline"):
            if (TODAY - dt.date.fromisoformat(first)).days > cfg.get("open_until_filled_days", 120):
                continue
        r["country"] = country_name(r.get("country", ""))
        r["deadline_status"], r["days_left"] = st, days
        r["region"] = region_for(r["country"])
        text = r.pop("classify_text", "") or " ".join(str(r.get(k, "")) for k in ("title", "department", "subject_area", "funding_text"))
        tags = classify_item(text)
        r["field"], r["subfields"] = tags["field"], tags["subfields"]
        r["intake_year"] = intake_year(r.get("start_text", ""))
        r["annual_usd_approx"] = annual_usd(r.get("funding_text", ""), rates)
        r["intl"] = r.get("intl") or intl_status(r.get("title", ""), r.get("funding_text", ""), r.get("eligibility", ""), r.get("description", ""))
        r["first_seen"] = first
        r["checked"] = r.pop("source_checked", "") or (TODAY.isoformat() if r.get("source_name") == "EURAXESS" else first)
        out.append(r)
    out.sort(key=lambda r: (r["days_left"] is None, r["days_left"] or 0))
    return out


# ---------------------------------------------------------------- supervisors
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
SOURCE_LINK = {"NIH (USA)": "NIH RePORTER", "NSF (USA)": "NSF Award Search", "ARC (Australia)": "Australian Research Council"}


def build_mentors(grants: list[dict], positions: list[dict], first_seen: dict) -> list[dict]:
    people: dict[str, dict] = {}

    def get(name, inst, country, city=""):
        k = person_key(name, inst)
        if k not in people:
            people[k] = {"id": slug(name, inst), "name": name, "institution": inst, "city": city,
                         "country": country_name(country), "region": region_for(country), "department": "",
                         "topics": [], "signal": "research_grant", "grants": [], "positions": [],
                         "metrics": None, "papers": [], "sources": set(), "_text": "", "contacts": []}
        return people[k]

    for p in positions:
        for name, other_inst in split_people(p.get("supervisor", "")):
            m = get(name, other_inst or p.get("university", ""), p.get("country", ""), "" if other_inst else p.get("city", ""))
            m["positions"].append(p["id"])
            m["signal"] = "open_position"
            if p.get("department") and not m["department"]:
                m["department"], m["department_source"] = p["department"], p.get("source_name", "")
            if p.get("contact_email") and not any(c["email"] == p["contact_email"] for c in m["contacts"]):
                m["contacts"].append({"email": p["contact_email"], "source": p.get("source_name", "") + " advert", "url": p.get("url", "")})
            m["sources"].add(p.get("source_name", ""))
            m["_text"] += " " + p.get("title", "")
    for g in grants:
        m = get(g["pi_name"], g["institution"], g["country"], g.get("city", ""))
        m["grants"].append({k: g[k] for k in ("agency", "number", "title", "amount", "currency", "start", "end", "program", "kind", "url")})
        if g.get("department") and not m["department"]:
            m["department"] = g["department"]
            m["department_source"] = SOURCE_LINK.get(g["agency"], g["agency"])
        if g.get("pi_email") and not any(c["email"] == g["pi_email"] for c in m["contacts"]):
            # Only emails that an official public record itself publishes; never guessed or built.
            m["contacts"].append({"email": g["pi_email"], "source": SOURCE_LINK.get(g["agency"], g["agency"]) + " award record", "url": g["url"]})
        m["_text"] = (m["_text"] + " " + g["title"] + " " + g.get("terms", ""))[:3000]
        sig = "training_grant" if g["kind"] == "training" else "research_grant"
        if SIGNAL_RANK[sig] > SIGNAL_RANK[m["signal"]]:
            m["signal"] = sig
        m["sources"].add(SOURCE_LINK.get(g["agency"], g["agency"]))

    out = []
    for m in people.values():
        m["grants"].sort(key=lambda g: (g["kind"] != "training", -g["amount"]))
        m["grants"] = m["grants"][:6]
        m["signal_label"] = SIGNAL_LABEL[m["signal"]]
        m["sources"] = sorted(s for s in m["sources"] if s)
        m["total_active_funding_usd"] = round(sum(g["amount"] for g in m["grants"] if g["currency"] == "USD"))
        m["first_seen"] = first_seen.setdefault("m:" + m["id"], TODAY.isoformat())
        m["checked"] = TODAY.isoformat()
        out.append(m)
    out.sort(key=lambda m: (-SIGNAL_RANK[m["signal"]], m["name"].split()[-1] if m["name"].split() else ""))
    return out


def apply_removals(mentors: list[dict], positions: list[dict]) -> int:
    """data/curated/removals.json: {"hide_emails": [...], "hide_people": ["<mentor id>", ...]} honoured on every run."""
    rm = load_json(CURATED / "removals.json", {})
    hide_e = {e.lower() for e in rm.get("hide_emails", [])}
    hide_p = set(rm.get("hide_people", []))
    for m in mentors:
        m["contacts"] = [c for c in m.get("contacts", []) if c["email"].lower() not in hide_e]
    for p in positions:
        if (p.get("contact_email") or "").lower() in hide_e:
            p["contact_email"] = ""
    before = len(mentors)
    mentors[:] = [m for m in mentors if m["id"] not in hide_p]
    return before - len(mentors)


def tag_mentors(mentors: list[dict]) -> None:
    for m in mentors:
        oa = T.from_openalex(m.get("oa_subfields") or [])
        txt = T.from_text(m.pop("_text", "") + " " + " ".join(m.get("topics") or []))
        tags = T.merge(oa, txt)
        m["field"], m["subfields"] = tags["field"], tags["subfields"]
        m["tagged_by"] = "OpenAlex publication topics" if oa else "grant and advert keywords"
        m.pop("oa_subfields", None)


def build_funding(rates) -> list[dict]:
    rows = load_json(CURATED / "scholarships.json", [])
    for r in rows:
        st, days = deadline_status(r.get("deadline", ""))
        r["deadline_status"] = "check" if not r.get("deadline") else st
        r["days_left"] = days
        r["annual_usd_approx"] = annual_usd(r.get("stipend_text", ""), rates)
        r["intake_year"] = intake_year(r.get("intake", ""))
        r["intl"] = "international" if re.search(r"any nationality|worldwide|international|outside the|non-[A-Z]|countries", r.get("eligible", "")) else ""
        r["checked"] = r.get("checked") or ""
    return rows


# ---------------------------------------------------------------- output
def shard_of(mid: str) -> int:
    return int(hashlib.sha1(mid.encode()).hexdigest()[:6], 16) % SHARDS


SIG_CODE = {"open_position": "o", "training_grant": "t", "research_grant": "g"}


def write_mentors(out: pathlib.Path, mentors: list[dict]) -> None:
    index, shards = [], [dict() for _ in range(SHARDS)]
    for m in mentors:
        h = shard_of(m["id"])
        index.append({"i": m["id"], "n": m["name"], "u": m["institution"], "c": m["country"], "r": m["region"],
                      "f": m["field"], "s": m["subfields"], "g": SIG_CODE[m["signal"]],
                      "m": m["total_active_funding_usd"], "p": len(m["positions"]), "d": m["first_seen"],
                      "t": (m.get("topics") or [])[:3], "k": 1 if m.get("papers") else 0, "h": h,
                      "w": " / ".join(g["title"] for g in m["grants"][:2])[:160]})
        shards[h][m["id"]] = m
    folder = out / "mentors"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for i, sh in enumerate(shards):
        save_json(folder / f"{i:02d}.json", sh, compact=True)
    save_json(out / "mentors-index.json", index, compact=True)
    old = out / "mentors.json"
    if old.exists():
        old.unlink()


def subject_counts(mentors, positions) -> list[dict]:
    counts: dict[str, int] = {}
    fcounts: dict[str, int] = {}
    for r in mentors + positions:
        fcounts[r["field"]] = fcounts.get(r["field"], 0) + 1
        for s in r["subfields"]:
            counts[s] = counts.get(s, 0) + 1
    tree = T.public_tree()
    for f in tree:
        f["n"] = fcounts.get(f["id"], 0)
        for s in f["subfields"]:
            s["n"] = counts.get(s["id"], 0)
    return tree


def build_us_programs() -> list[dict]:
    """Hand-checked US PhD program facts (data/curated/us_programs.json), with days left to the deadline."""
    rows = load_json(CURATED / "us_programs.json", {}).get("programs", [])
    for r in rows:
        try:
            r["days_left"] = (dt.date.fromisoformat(r["deadline"]) - TODAY).days if r.get("deadline") else None
        except ValueError:
            r["days_left"] = None
    return rows


def main() -> int:
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", default=str(OUT), help="folder for the data files (default site/data)")
    args = ap.parse_args()
    OUT = pathlib.Path(args.out)

    cfg = yaml.safe_load((ROOT / "pipeline" / "config.yaml").read_text())
    # Test bench only: PMF_FORCE_SOURCES=arc,euraxess switches sources on for a scratch build
    # (used by the manual "Probe" workflow, which never publishes).
    import os
    for name in filter(None, os.environ.get("PMF_FORCE_SOURCES", "").split(",")):
        cfg["sources"][name.strip()] = True
    http = Http(cfg.get("contact_email", "anonymous@example.com"))
    rates = cfg.get("usd_rates", {})
    health = Health(persist=not args.offline)
    first_seen = load_json(CACHE / "first_seen.json", {})
    prev_meta = load_json(OUT / "meta.json", {})
    prev_counts = prev_meta.get("counts") or {}

    grants = collect_grants(cfg, http, args.offline, health)
    positions = collect_positions(cfg, http, args.offline, health, rates, first_seen)
    mentors = build_mentors(grants, positions, first_seen)
    apply_removals(mentors, positions)

    if cfg["sources"].get("openalex") and not args.offline:
        http.budget(cfg.get("openalex_minutes", 40))
        try:
            import os
            key = os.environ.get("OPENALEX_API_KEY", "")
            st = OA.enrich(http, mentors, cfg.get("contact_email", ""), max_lookups=cfg.get("openalex_max_lookups", 2500), api_key=key)
            have = sum(1 for m in mentors if m.get("metrics"))
            health.ok("OpenAlex", have or 1, f"{st['lookups']} new lookups today ({st['matched']} matched); {have} supervisors have profiles"
                      + ("; daily allowance used up, the rest continue tomorrow" if st["stopped_early"] else "")
                      + ("" if key else "; no API key (add secret OPENALEX_API_KEY for a higher allowance)"))
        except Exception as ex:  # noqa: BLE001
            health.failed("OpenAlex", str(ex), 0)
        finally:
            http.budget(None)
    else:
        cache = load_json(CACHE / "openalex.json", {})
        for m in mentors:
            if m["id"] in cache:
                OA.apply_cached(m, cache[m["id"]])
        if not cfg["sources"].get("openalex"):
            health.off("OpenAlex")
    tag_mentors(mentors)
    funding = build_funding(rates)
    if not args.offline and cfg.get("check_scholarship_pages", True):
        http.budget(6)
        try:
            health.check_scholarships(http, funding)
        finally:
            http.budget(None)

    programs = build_us_programs()
    if not args.offline and cfg.get("check_scholarship_pages", True):
        http.budget(4)
        try:
            health.check_scholarships(http, [{"id": "usp-" + p["id"], "name": "US program guide: " + p["university"] + " – " + p["program"],
                                              "url": p["url"], "days_left": p.get("days_left")} for p in programs if p.get("monitor")])
        finally:
            http.budget(None)

    counts = {"positions": len(positions), "mentors": len(mentors), "funding": len(funding), "grants": len(grants)}

    # Safety: never publish a collapsed dataset.
    aborted = ""
    for key, floor in (("mentors", 0.4), ("positions", 0.3), ("funding", 0.5)):
        before = prev_counts.get(key, 0)
        if before > 20 and counts[key] < before * floor:
            aborted = f"{key} fell from {before} to {counts[key]}"
    if aborted and not args.offline:
        health.write(OUT, counts, prev_counts, aborted=aborted)
        print(f"ABORT: {aborted}. Keeping previous data.", file=sys.stderr)
        return 2

    meta = {"generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "data_date": TODAY.isoformat(), "counts": counts,
            "subjects": subject_counts(mentors, positions),
            "countries": sorted({r["country"] for r in positions + mentors if r.get("country")}),
            "intake_years": sorted({r["intake_year"] for r in positions + funding if r.get("intake_year")}),
            "offline": args.offline}
    report = health.write(OUT, counts, prev_counts)
    meta["source_status"] = {k: f"{v['status']} ({v.get('count', 0)})" for k, v in report["sources"].items()}
    meta["health"] = report["overall"]

    save_json(OUT / "positions.json", positions, compact=True)
    save_json(OUT / "funding.json", funding)
    save_json(OUT / "us_programs.json", {**load_json(CURATED / "us_programs.json", {}), "programs": programs})
    write_mentors(OUT, mentors)
    save_json(OUT / "meta.json", meta)
    if not args.offline:
        save_json(CACHE / "first_seen.json", first_seen, compact=True)
    print(json.dumps(counts), json.dumps(report["sources"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
