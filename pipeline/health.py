"""Data health tracking for the daily run.

Each source reports ok / failed / off / held with a record count. State is remembered in
pipeline/cache/source_state.json so we can tell how long a source has been failing and
whether its count collapsed. The result is written to site/data/health.json, which the
weekly Claude check and the GitHub issue step both read.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re

from common import TODAY, Http

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / "pipeline" / "cache" / "source_state.json"
PAGES = ROOT / "pipeline" / "cache" / "scholarship_pages.json"


class Health:
    def __init__(self, persist: bool = True):
        self.persist = persist
        try:
            self.state = json.loads(STATE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {}
        self.sources: dict[str, dict] = {}
        self.warnings: list[str] = []
        self.review: list[dict] = []

    def ok(self, name: str, count: int, note: str = ""):
        prev = self.state.get(name, {})
        entry = {"status": "ok", "count": count, "last_ok": TODAY.isoformat(), "note": note}
        if count == 0:
            entry["status"] = "empty"
            self.warnings.append(f"{name}: returned 0 records; last good copy kept")
        elif prev.get("last_ok_count") and count < prev["last_ok_count"] * 0.5:
            self.warnings.append(f"{name}: count fell from {prev['last_ok_count']} to {count}")
        self.sources[name] = entry
        if count:
            self.state[name] = {"last_ok": TODAY.isoformat(), "last_ok_count": count, "fail_streak": 0}
        else:
            self._failed_streak(name)

    def failed(self, name: str, error: str, kept: int):
        streak = self._failed_streak(name)
        last_ok = self.state.get(name, {}).get("last_ok", "never")
        self.sources[name] = {"status": "failed", "count": kept, "last_ok": last_ok, "note": f"kept last good copy; {error[:160]}"}
        self.warnings.append(f"{name}: failed ({streak} day(s) in a row), showing last good copy from {last_ok} — {error[:120]}")

    def off(self, name: str, note: str = "switched off in config.yaml"):
        self.sources[name] = {"status": "off", "count": 0, "note": note}

    def held(self, name: str, count: int, note: str):
        self.sources[name] = {"status": "held", "count": count, "note": note}

    def _failed_streak(self, name: str) -> int:
        st = self.state.setdefault(name, {})
        st["fail_streak"] = st.get("fail_streak", 0) + 1
        return st["fail_streak"]

    # ------------------------------------------------------------ scholarships
    def check_scholarships(self, http: Http, rows: list[dict], max_pages: int = 40):
        """Flag official pages whose key lines changed, deadlines that passed, or pages that broke."""
        try:
            seen = json.loads(PAGES.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            seen = {}
        key_rx = re.compile(r"(deadline|closing|close[sd]?|open[s]?|stipend|allowance|per month|monthly|£|€|\$|20\d\d|apply)", re.I)
        for r in rows[:max_pages]:
            url, sid = r.get("url", ""), r.get("id", "")
            if r.get("days_left") is not None and r["days_left"] < 0:
                self.review.append({"id": sid, "name": r.get("name"), "url": url, "reason": "deadline has passed: roll over to the next round"})
            if not url:
                continue
            try:
                page = http.get_text(url)
            except RuntimeError as ex:
                prev = seen.get(sid, {})
                prev["fails"] = prev.get("fails", 0) + 1
                seen[sid] = prev
                if prev["fails"] >= 3:
                    self.review.append({"id": sid, "name": r.get("name"), "url": url, "reason": f"official page unreachable 3+ days: {str(ex)[:80]}"})
                continue
            text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S)
            text = re.sub(r"<[^>]+>", "\n", text)
            lines = sorted({re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if key_rx.search(ln)})
            lines = [ln for ln in lines if 8 < len(ln) < 400]
            digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
            prev = seen.get(sid, {})
            if prev.get("hash") and prev["hash"] != digest:
                self.review.append({"id": sid, "name": r.get("name"), "url": url, "reason": "official page changed (dates or amounts may have changed)"})
            seen[sid] = {"hash": digest, "checked": TODAY.isoformat(), "fails": 0}
        PAGES.parent.mkdir(exist_ok=True)
        PAGES.write_text(json.dumps(seen, indent=0, sort_keys=True))

    # ------------------------------------------------------------ output
    def write(self, out_dir: pathlib.Path, counts: dict, prev_counts: dict, aborted: str = "") -> dict:
        for name, st in self.state.items():
            if self.sources.get(name, {}).get("status") == "failed" and st.get("fail_streak", 0) >= 3:
                pass  # already in warnings with the streak
        level = "ok"
        if self.warnings or self.review:
            level = "warning"
        if aborted or any(s.get("status") == "failed" and self.state.get(n, {}).get("fail_streak", 0) >= 3 for n, s in self.sources.items()):
            level = "error"
        report = {
            "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "overall": level, "aborted": aborted, "counts": counts, "previous_counts": prev_counts,
            "sources": self.sources, "warnings": self.warnings, "scholarships_to_review": self.review[:15],
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "health.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
        if self.persist:
            STATE.parent.mkdir(exist_ok=True)
            STATE.write_text(json.dumps(self.state, indent=1, sort_keys=True))
        return report
