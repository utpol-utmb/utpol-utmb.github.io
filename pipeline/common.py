"""Shared helpers: HTTP with retries, subject classification, dates, slugs."""
from __future__ import annotations

import datetime as dt
import re
import time
import unicodedata

import urllib.parse
import urllib.robotparser

import requests

TODAY = dt.date.today()

SUBJECTS = [
    "Ageing & Palliative Care",
    "Public Health & Epidemiology",
    "Health Data Science & Digital Health",
    "Infectious Disease & One Health",
    "Biomedical & Life Sciences",
    "Computer Science & AI",
    "Engineering",
    "Environmental & Earth Sciences",
    "Social Sciences & Economics",
    "Physical Sciences & Mathematics",
]

# keyword stems -> subject. Scored; the subject with most hits wins,
# ties go to the earlier subject in SUBJECTS (health areas first).
_KEYWORDS = {
    "Ageing & Palliative Care": ["aging", "ageing", "dementia", "alzheimer", "palliative", "hospice",
                                  "end-of-life", "end of life", "gerontolog", "older adult", "frailty", "geriatric"],
    "Public Health & Epidemiology": ["epidemiolog", "public health", "population health", "health services", "community", "prevention", "intervention", "behavioral", "disparit", "survey",
                                     "health policy", "biostatist", "cohort", "health dispar", "homeless"],
    "Health Data Science & Digital Health": ["digital health", "health data", "electronic health", "ehr",
                                             "wearable", "informatics", "risk prediction", "pathology foundation",
                                             "clinical data", "digital twin", "mhealth", "telehealth"],
    "Infectious Disease & One Health": ["infectious", "pathogen", "virus", "viral", "virolog", "zoonot",
                                        "epidemic", "one health", "antimicrobial", "host-pathogen",
                                        "phylodynamic", "immunolog", "vaccine", "wastewater", "metagenomic"],
    "Biomedical & Life Sciences": ["cancer", "cell", "protein", "molecular", "genom", "biolog", "neuro", "tumor", "gene", "receptor", "signaling", "mouse", "tissue", "immune", "drug", "pharmac", "clinical", "disease", "patient", "therap",
                                   "metabolic", "biologics", "microbio", "t-cell", "insulin", "biomanufactur"],
    "Computer Science & AI": ["machine learning", "artificial intelligence", " ai ", "ai-", "deep learning",
                              "neural network", "cyber", "software", "computing", "data-driven",
                              "robot", "generative", "foundation model", "large language"],
    "Engineering": ["engineering", "polymer", "microelectronic", "sensor", "circuit", "material", "implant",
                    "mobility", "manufactur", "nanoscale"],
    "Environmental & Earth Sciences": ["climate", "ecolog", "wildfire", "forest", "atmospher", "ice core",
                                       "conservation", "environment", "water", "biodivers", "geo", "arctic",
                                       "soil", "wildlife", "disaster"],
    "Social Sciences & Economics": ["social", "economic", "political", "education", "workforce", "history",
                                    "governance", "psycholog", "reparation", "activism", "stem identit", "scholars", "mentorship", "careers"],
    "Physical Sciences & Mathematics": ["mathemat", "statistic", "physics", "quantum", "chemi", "algebra",
                                        "geometry", "change-point", "differential", "network dynamics"],
}


# Broad words that appear in almost any biomedical or health grant count for less.
_WEAK = {"cell", "gene", "receptor", "signaling", "mouse", "tissue", "immune", "drug", "pharmac", "clinical",
         "disease", "patient", "therap", "biolog", "molecular", "community", "prevention", "intervention",
         "behavioral", "survey", "social", "water", "geo", "material"}


def classify(text: str) -> str:
    t = f" {text.lower()} "
    best, best_score = "", 0
    for subject in SUBJECTS:
        score = sum(min(t.count(k), 4) * (0.34 if k in _WEAK else 1) for k in _KEYWORDS[subject])
        if score > best_score:
            best, best_score = subject, score
    return best or "Other"


US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
                "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR GU VI".split())

# ISO code -> (country name, region). Used to normalise countries from every source.
COUNTRIES = {
    "GB": ("United Kingdom", "Europe"), "UK": ("United Kingdom", "Europe"), "IE": ("Ireland", "Europe"), "DE": ("Germany", "Europe"),
    "FR": ("France", "Europe"), "NL": ("Netherlands", "Europe"), "BE": ("Belgium", "Europe"), "LU": ("Luxembourg", "Europe"),
    "CH": ("Switzerland", "Europe"), "AT": ("Austria", "Europe"), "SE": ("Sweden", "Europe"), "NO": ("Norway", "Europe"),
    "DK": ("Denmark", "Europe"), "FI": ("Finland", "Europe"), "IS": ("Iceland", "Europe"), "ES": ("Spain", "Europe"),
    "PT": ("Portugal", "Europe"), "IT": ("Italy", "Europe"), "GR": ("Greece", "Europe"), "EL": ("Greece", "Europe"),
    "CY": ("Cyprus", "Europe"), "MT": ("Malta", "Europe"), "PL": ("Poland", "Europe"), "CZ": ("Czechia", "Europe"),
    "SK": ("Slovakia", "Europe"), "HU": ("Hungary", "Europe"), "SI": ("Slovenia", "Europe"), "HR": ("Croatia", "Europe"),
    "RO": ("Romania", "Europe"), "BG": ("Bulgaria", "Europe"), "EE": ("Estonia", "Europe"), "LV": ("Latvia", "Europe"),
    "LT": ("Lithuania", "Europe"), "RS": ("Serbia", "Europe"), "UA": ("Ukraine", "Europe"), "TR": ("Türkiye", "Middle East"),
    "US": ("United States", "North America"), "CA": ("Canada", "North America"), "MX": ("Mexico", "Latin America"),
    "BR": ("Brazil", "Latin America"), "AR": ("Argentina", "Latin America"), "CL": ("Chile", "Latin America"),
    "CO": ("Colombia", "Latin America"), "PE": ("Peru", "Latin America"), "AU": ("Australia", "Oceania"),
    "NZ": ("New Zealand", "Oceania"), "JP": ("Japan", "Asia"), "KR": ("South Korea", "Asia"), "CN": ("China", "Asia"),
    "HK": ("Hong Kong", "Asia"), "TW": ("Taiwan", "Asia"), "SG": ("Singapore", "Asia"), "MY": ("Malaysia", "Asia"),
    "TH": ("Thailand", "Asia"), "VN": ("Vietnam", "Asia"), "ID": ("Indonesia", "Asia"), "PH": ("Philippines", "Asia"),
    "IN": ("India", "Asia"), "BD": ("Bangladesh", "Asia"), "PK": ("Pakistan", "Asia"), "LK": ("Sri Lanka", "Asia"),
    "NP": ("Nepal", "Asia"), "IL": ("Israel", "Middle East"), "SA": ("Saudi Arabia", "Middle East"),
    "AE": ("United Arab Emirates", "Middle East"), "QA": ("Qatar", "Middle East"), "IR": ("Iran", "Middle East"),
    "EG": ("Egypt", "Africa"), "ZA": ("South Africa", "Africa"), "NG": ("Nigeria", "Africa"), "KE": ("Kenya", "Africa"),
    "GH": ("Ghana", "Africa"), "ET": ("Ethiopia", "Africa"), "UG": ("Uganda", "Africa"), "TZ": ("Tanzania", "Africa"),
    "RW": ("Rwanda", "Africa"), "MA": ("Morocco", "Africa"), "TN": ("Tunisia", "Africa"),
}
REGIONS = {name: region for name, region in COUNTRIES.values()}
_NAME_FIX = {"czech republic": "Czechia", "turkey": "Türkiye", "korea": "South Korea", "republic of korea": "South Korea",
             "usa": "United States", "united states of america": "United States", "uk": "United Kingdom",
             "the netherlands": "Netherlands", "great britain": "United Kingdom", "england": "United Kingdom",
             "scotland": "United Kingdom", "wales": "United Kingdom", "northern ireland": "United Kingdom"}


def country_name(value: str) -> str:
    """'GB', 'gb', 'England', 'United Kingdom' -> 'United Kingdom'. Unknown values pass through."""
    v = (value or "").strip()
    if len(v) == 2 and v.upper() in COUNTRIES:
        return COUNTRIES[v.upper()][0]
    return _NAME_FIX.get(v.lower(), v)


def region_for(country: str) -> str:
    return REGIONS.get(country_name(country), "Other")


def slug(*parts: str) -> str:
    s = " ".join(p for p in parts if p)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:80]


def person_key(name: str, institution: str) -> str:
    """Key used to merge the same person across sources."""
    n = re.sub(r"\b(dr|prof|professor|assoc|asst|mr|ms|mrs)\.?\b", "", name.lower())
    n = re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode())
    toks = n.split()
    short = f"{toks[0][0]}-{toks[-1]}" if len(toks) >= 2 else "-".join(toks)
    inst = re.sub(r"[^a-z]", "", institution.lower())[:18]
    return f"{short}|{inst}"


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%d %B %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(value[: len(value)], fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if m:
        return dt.date.fromisoformat(m.group(1))
    return None


def intake_year(*texts: str) -> int | None:
    for t in texts:
        if not t:
            continue
        m = re.search(r"\b(20[2-3]\d)\b", str(t))
        if m:
            return int(m.group(1))
    return None


class RobotsDisallowed(RuntimeError):
    pass


class Http:
    """requests.Session with retries, polite rate limiting and a robots.txt guard.

    Every request is checked against the site's robots.txt for our user agent first.
    A disallowed URL raises RobotsDisallowed and is never fetched.
    """

    AGENT = "PhDMentorFinder"

    def __init__(self, contact: str, pause: float = 0.25):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = f"{self.AGENT}/1.0 (+https://utpol-utmb.github.io; mailto:{contact})"
        self.pause = pause
        self.deadline = None
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(host + "/robots.txt", timeout=20)
                if r.status_code >= 400:  # no robots.txt (or none we can read) = no restrictions
                    rp = None
                else:
                    rp.parse(r.text.splitlines())
            except requests.RequestException:
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(self.AGENT, url)

    def _do(self, method: str, url: str, **kw):
        if self.deadline and time.time() > self.deadline:
            raise RuntimeError("time budget for this source used up")
        full = url
        if kw.get("params"):
            full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(kw["params"], doseq=True)
        if not self.allowed(full):
            raise RobotsDisallowed(f"robots.txt does not allow {full[:120]}")
        last = None
        for attempt in range(3):
            try:
                r = self.s.request(method, url, timeout=30, **kw)
            except requests.RequestException as e:  # network trouble: retry
                last = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt * 2)
                continue
            if r.status_code >= 400:  # a client error will not fix itself
                raise RuntimeError(f"{method} {url} -> HTTP {r.status_code}")
            time.sleep(self.pause)
            return r
        raise RuntimeError(f"{method} {url} failed: {last}")

    def budget(self, minutes: float | None):
        """Limit how long the current source may keep making requests."""
        self.deadline = time.time() + minutes * 60 if minutes else None

    def get_json(self, url: str, **kw):
        return self._do("GET", url, **kw).json()

    def post_json(self, url: str, payload: dict, **kw):
        return self._do("POST", url, json=payload, **kw).json()

    def get_text(self, url: str, **kw) -> str:
        return self._do("GET", url, **kw).text
