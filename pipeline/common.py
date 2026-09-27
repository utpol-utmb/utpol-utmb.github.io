"""Shared helpers: HTTP with retries, subject classification, dates, slugs."""
from __future__ import annotations

import datetime as dt
import re
import time
import unicodedata

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

REGIONS = {
    "United Kingdom": "Europe", "Ireland": "Europe", "Germany": "Europe", "France": "Europe", "Netherlands": "Europe",
    "Belgium": "Europe", "Switzerland": "Europe", "Sweden": "Europe", "Norway": "Europe", "Denmark": "Europe",
    "Finland": "Europe", "Spain": "Europe", "Italy": "Europe", "Austria": "Europe", "Portugal": "Europe",
    "Hungary": "Europe", "Poland": "Europe", "Czechia": "Europe",
    "United States": "North America", "Canada": "North America",
    "Australia": "Oceania", "New Zealand": "Oceania",
    "Japan": "Asia", "South Korea": "Asia", "China": "Asia", "Singapore": "Asia", "India": "Asia",
    "Türkiye": "Middle East",
}


def region_for(country: str) -> str:
    return REGIONS.get(country, "Other")


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


class Http:
    """requests.Session with retries and polite rate limiting."""

    def __init__(self, contact: str, pause: float = 0.25):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = f"PhDMentorFinder/1.0 (mailto:{contact})"
        self.pause = pause
        self.deadline = None

    def _do(self, method: str, url: str, **kw):
        if self.deadline and time.time() > self.deadline:
            raise RuntimeError("time budget for this source used up")
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
