import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "pipeline" / "sources"))

import build  # noqa: E402
import grants  # noqa: E402
from common import classify, person_key  # noqa: E402


def test_classify():
    assert classify("Palliative care for older adults with dementia") == "Ageing & Palliative Care"
    assert classify("Wastewater virology and epidemic prediction") == "Infectious Disease & One Health"
    assert classify("Deep learning for robotics") == "Computer Science & AI"


def test_money():
    rates = {"GBP": 1.27, "EUR": 1.08}
    assert build.annual_usd("£20,780 a year", rates) == round(20780 * 1.27)
    assert build.annual_usd("€4,010/month", rates) == round(4010 * 12 * 1.08)
    assert build.annual_usd("Competitive", rates) is None


def test_split_people():
    got = build.split_people("Dr Jack Stone; Professor Peter Vickerman; Dr Ian Thomas (Cardiff University)")
    assert got == [("Jack Stone", ""), ("Peter Vickerman", ""), ("Ian Thomas", "Cardiff University")]


def test_person_key_merges_titles():
    assert person_key("Prof. Jane Doe", "Univ of X") == person_key("Jane Doe", "Univ of X")


def test_nsf_skips_undergrad_and_conferences():
    raw = json.loads((ROOT / "pipeline/fixtures/nsf_sample.json").read_text())["response"]["award"]
    recs = grants.nsf_normalize(raw)
    assert recs and not any("REU Site" in r["title"] or r["title"].startswith("Conference") for r in recs)
    assert any(r["kind"] == "training" for r in recs)


def test_nih_normalize_shape():
    row = {"appl_id": 1, "project_num": "5T32AG000001-05", "project_title": "Training in aging research",
           "principal_investigators": [{"full_name": "JANE  DOE"}],
           "organization": {"org_name": "UNIV OF TEXAS MEDICAL BRANCH", "org_state": "TX", "org_country": "UNITED STATES"},
           "award_amount": 500000, "project_start_date": "2024-07-01T00:00:00", "project_end_date": "2029-06-30T00:00:00",
           "activity_code": "T32", "agency_ic_admin": {"abbreviation": "NIA"}}
    r = grants.nih_normalize([row])[0]
    assert r["pi_name"] == "Jane Doe" and r["kind"] == "training" and r["end"] == "2029-06-30"


def test_offline_build_runs(tmp_path):
    res = subprocess.run([sys.executable, str(ROOT / "pipeline/build.py"), "--offline", "--out", str(tmp_path)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["counts"]["positions"] > 0 and meta["counts"]["mentors"] > 0


def test_ukri_normalize_shape():
    comp = {"project": {"id": "x", "title": "Ageing well", "status": None, "grantCategory": "Studentship",
                        "grantReference": "MR/1", "fund": {"valuePounds": 0, "start": 1.7e12, "end": 1.9e12,
                                                           "funder": {"name": "MRC"}}},
            "principalInvestigators": [], "supervisors": [{"fullName": "Jane Doe"}],
            "leadResearchOrganisation": {"name": "University of Sheffield"}}
    r = grants.ukri_normalize([comp])[0]
    assert r["pi_name"] == "Jane Doe" and r["kind"] == "training" and r["country"] == "United Kingdom"


# ---------------------------------------------------------------- new in Oct 2026
import taxonomy as T  # noqa: E402


def test_taxonomy_loads_and_validates_codes():
    tax = T.load()
    assert len(tax["fields"]) >= 14
    assert all(any(s["id"].endswith("-general") for s in f["subfields"]) for f in tax["fields"])
    assert T.search_terms() and len(T.search_terms(for_nih=True)) < len(T.search_terms())


def test_taxonomy_never_drops_items():
    assert T.from_text("Something about nothing") == {"field": "other", "subfields": ["other-general"]}
    assert T.from_text("Public health studentship")["subfields"] == ["public-health-general"]


def test_taxonomy_multi_tags_and_openalex():
    r = T.from_text("Palliative care for older adults with dementia")
    assert "palliative-care" in r["subfields"] and "aging-gerontology" in r["subfields"]
    oa = T.from_openalex([{"subfield": 2739, "count": 72}, {"subfield": 2717, "count": 30}])
    assert oa["field"] == "public-health" and "aging-gerontology" in oa["subfields"]


def test_intl_status():
    assert build.intl_status("Fully funded studentship for Home fee students only") == "home"
    assert build.intl_status("Open to all nationalities") == "international"
    assert build.intl_status("PhD in chemistry") == ""


def test_euraxess_detail_parser():
    import euraxess
    page = ('<h1 class="x">PhD position in coastal ecology</h1>'
            '<dt class="ecl-description-list__term">Organisation/Company</dt><dd class="ecl-description-list__definition"><div>CNRS</div></dd>'
            '<dt class="ecl-description-list__term">Researcher Profile</dt><dd class="ecl-description-list__definition"><div>First Stage Researcher (R1)</div></dd>'
            '<dt class="ecl-description-list__term">Application Deadline</dt><dd class="ecl-description-list__definition"><div><time datetime="2030-10-24T23:59:00+00:00">24 Oct</time></div></dd>'
            '<dt class="ecl-description-list__term">Country</dt><dd class="ecl-description-list__definition"><div>France</div></dd>')
    d = euraxess.parse_detail("1", page)
    assert d["organisation"] == "CNRS" and d["deadline"] == "2030-10-24" and d["country"] == "France"
    pos = euraxess.to_positions([d | {"description": ""}])
    assert pos and pos[0]["source_name"] == "EURAXESS" and pos[0]["url"].endswith("/jobs/1")


def test_offline_build_writes_index_and_health(tmp_path):
    res = subprocess.run([sys.executable, str(ROOT / "pipeline/build.py"), "--offline", "--out", str(tmp_path)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    idx = json.loads((tmp_path / "mentors-index.json").read_text())
    assert idx and {"i", "n", "f", "s", "h"} <= set(idx[0])
    shard = json.loads((tmp_path / "mentors" / f"{idx[0]['h']:02d}.json").read_text())
    assert idx[0]["i"] in shard
    health = json.loads((tmp_path / "health.json").read_text())
    assert health["overall"] in ("ok", "warning", "error") and "sources" in health
    pos = json.loads((tmp_path / "positions.json").read_text())
    assert all(p["field"] and p["subfields"] for p in pos)
    assert not any(p.get("source_name") == "jobs.ac.uk" for p in pos)
