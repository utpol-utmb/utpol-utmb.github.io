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


def test_offline_build_runs():
    res = subprocess.run([sys.executable, str(ROOT / "pipeline/build.py"), "--offline"], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    meta = json.loads((ROOT / "site/data/meta.json").read_text())
    assert meta["counts"]["positions"] > 0 and meta["counts"]["mentors"] > 0
