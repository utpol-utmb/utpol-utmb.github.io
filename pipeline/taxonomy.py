"""Field > Subfield classification driven by pipeline/taxonomy.yaml.

Two routes:
  * from_openalex(topics)  - for researchers matched in OpenAlex: their own paper topics
                             carry OpenAlex subfield codes, mapped through the yaml.
  * from_text(text)        - for grant titles and job adverts: keyword scoring.

Both return {"field": <field id>, "subfields": [<subfield id>, ...]} where subfields
has 1-3 entries. Items that fit a field but no subfield get "<field>-general";
items that fit nothing get field "other" / subfield "other-general". Nothing is dropped.
"""
from __future__ import annotations

import functools
import json
import pathlib
import re

import yaml

HERE = pathlib.Path(__file__).resolve().parent
OTHER = {"field": "other", "subfields": ["other-general"]}


@functools.lru_cache(maxsize=1)
def load() -> dict:
    data = yaml.safe_load((HERE / "taxonomy.yaml").read_text())
    ref = {r["id"]: r for r in json.loads((HERE / "reference" / "openalex_subfields.json").read_text())}
    fields, sub_by_id, oa_sub, oa_field = [], {}, {}, {}
    seen = set()
    for f in data["fields"]:
        if f["id"] in seen:
            raise ValueError(f"duplicate field id {f['id']}")
        seen.add(f["id"])
        subs = []
        for s in f.get("subfields", []):
            if s["id"] in seen:
                raise ValueError(f"duplicate subfield id {s['id']}")
            seen.add(s["id"])
            for code in s.get("openalex", []) or []:
                if code not in ref:
                    raise ValueError(f"{s['id']}: unknown OpenAlex subfield code {code}")
                oa_sub[code] = (f["id"], s["id"])
            kws = [k.lower() for k in (s.get("keywords") or [])]
            entry = {"id": s["id"], "name": s["name"], "field": f["id"], "keywords": kws,
                     "search": s.get("search") or [], "openalex": s.get("openalex") or []}
            sub_by_id[s["id"]] = entry
            subs.append(entry)
        gen = {"id": f["id"] + "-general", "name": "General", "field": f["id"],
               "keywords": [k.lower() for k in (f.get("keywords") or [])], "search": [], "openalex": []}
        sub_by_id[gen["id"]] = gen
        for code in f.get("openalex_fields", []) or []:
            oa_field[code] = f["id"]
        fields.append({"id": f["id"], "name": f["name"], "nih": f.get("nih", True), "subfields": subs + [gen]})
    fields.append({"id": "other", "name": "Other", "nih": False,
                   "subfields": [{"id": "other-general", "name": "General", "field": "other", "keywords": [], "search": [], "openalex": []}]})
    sub_by_id["other-general"] = fields[-1]["subfields"][0]
    return {"fields": fields, "sub": sub_by_id, "oa_sub": oa_sub, "oa_field": oa_field, "ref": ref}


def field_name(fid: str) -> str:
    return next((f["name"] for f in load()["fields"] if f["id"] == fid), "Other")


def public_tree() -> list[dict]:
    """Compact tree for the app: [{id, name, subfields: [{id, name}]}]."""
    return [{"id": f["id"], "name": f["name"], "subfields": [{"id": s["id"], "name": s["name"]} for s in f["subfields"]]}
            for f in load()["fields"]]


def search_terms(for_nih: bool = False) -> list[str]:
    out = []
    for f in load()["fields"]:
        if for_nih and not f["nih"]:
            continue
        for s in f["subfields"]:
            out += s["search"]
    return list(dict.fromkeys(out))


def _pick(scores: dict[str, float], min_share: float = 0.2, top: int = 3) -> dict:
    if not scores:
        return dict(OTHER)
    tax = load()
    by_field: dict[str, float] = {}
    for sid, sc in scores.items():
        f = tax["sub"][sid]["field"]
        by_field[f] = by_field.get(f, 0) + sc
    field = max(by_field, key=lambda k: (by_field[k], -list(by_field).index(k)))
    in_field = sorted(((sc, sid) for sid, sc in scores.items() if tax["sub"][sid]["field"] == field), reverse=True)
    best = in_field[0][0]
    subs = [sid for sc, sid in in_field if sc >= best * min_share and not sid.endswith("-general")][:top]
    if not subs:
        subs = [field + "-general"]
    # also tag strong subfields from other fields (cross-disciplinary items)
    total = sum(scores.values())
    extra = [sid for sid, sc in sorted(scores.items(), key=lambda x: -x[1])
             if tax["sub"][sid]["field"] != field and sc >= total * 0.25 and not sid.endswith("-general")]
    return {"field": field, "subfields": (subs + extra)[:top]}


def from_openalex(topics: list[dict]) -> dict | None:
    """topics: [{"subfield": <int code>, "count": <int>}] from the author's OpenAlex record."""
    tax = load()
    scores: dict[str, float] = {}
    for t in topics or []:
        code, n = t.get("subfield"), float(t.get("count") or 1)
        if code in tax["oa_sub"]:
            scores[tax["oa_sub"][code][1]] = scores.get(tax["oa_sub"][code][1], 0) + n
        else:
            ref = tax["ref"].get(code)
            f = tax["oa_field"].get(ref["field"]) if ref else None
            if f:
                scores[f + "-general"] = scores.get(f + "-general", 0) + n * 0.8
    return _pick(scores) if scores else None


@functools.lru_cache(maxsize=1)
def _kw_index():
    rows = []
    for sid, s in load()["sub"].items():
        for k in s["keywords"]:
            if k.startswith(" ") or k.endswith(" "):
                rx = re.compile(re.escape(k))
            else:
                rx = re.compile(r"\b" + re.escape(k))
            w = 2.0 if " " in k.strip() else 1.0
            if sid.endswith("-general"):
                w *= 0.6  # broad field words count less than specific subfield words
            rows.append((sid, rx, w))
    return rows


def from_text(text: str) -> dict:
    t = f" {(text or '').lower()} "
    scores: dict[str, float] = {}
    for sid, rx, w in _kw_index():
        n = len(rx.findall(t))
        if n:
            scores[sid] = scores.get(sid, 0) + min(n, 3) * w
    return _pick(scores)


def merge(primary: dict | None, secondary: dict | None) -> dict:
    """Prefer OpenAlex (primary); fall back to text classification."""
    if primary and primary["field"] != "other":
        if secondary and secondary["field"] == primary["field"]:
            extra = [s for s in secondary["subfields"] if s not in primary["subfields"] and not s.endswith("-general")]
            subs = [s for s in primary["subfields"] if not s.endswith("-general")] + extra
            return {"field": primary["field"], "subfields": (subs or primary["subfields"])[:3]}
        return primary
    return secondary or dict(OTHER)
