"""Writes site/.well-known/assetlinks.json from android/fingerprints.txt.
This file proves to Android that the Play Store app and the website belong together."""
import json, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
fps = [l.strip() for l in (root / "android/fingerprints.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
out = [{"relation": ["delegate_permission/common.handle_all_urls"],
        "target": {"namespace": "android_app", "package_name": "org.phdmentorfinder.app", "sha256_cert_fingerprints": fps}}]
p = root / "site/.well-known/assetlinks.json"
p.parent.mkdir(exist_ok=True)
p.write_text(json.dumps(out, indent=2))
print(p.read_text())
