#!/usr/bin/env python3
"""Builds store-ready zips from the extension folder.

    python tools/package_extension.py --gecko-id media-catcher@your-name

Creates, inside dist/:
    media-catcher-chromium-<version>.zip   for Microsoft Edge Add-ons (also Chrome, Opera, Brave, Vivaldi)
    media-catcher-firefox-<version>.zip    for Firefox Add-ons (AMO)

The two builds differ only in manifest.json (Chromium needs background.service_worker,
Firefox needs background.scripts plus an add-on id).
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)  # same input -> byte-identical zip


def read_manifest() -> dict:
    return json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))


def chromium_manifest(m: dict) -> dict:
    m = json.loads(json.dumps(m))
    m["background"] = {"service_worker": "background.js"}
    m.pop("browser_specific_settings", None)
    return m


def firefox_manifest(m: dict, gecko_id: str) -> dict:
    m = json.loads(json.dumps(m))
    m["background"] = {"scripts": ["background.js"]}
    m["browser_specific_settings"] = {
        "gecko": {
            "id": gecko_id,
            "strict_min_version": "140.0",
            # Media Catcher collects and transmits no personal data (see PRIVACY.md)
            "data_collection_permissions": {"required": ["none"]},
        }
    }
    return m


def write_zip(out: Path, manifest: dict) -> None:
    files = sorted(p for p in EXT.rglob("*")
                   if p.is_file() and p.name != "manifest.json"
                   and not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(EXT).parts))
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def add(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        add("manifest.json", (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
        for p in files:
            add(p.relative_to(EXT).as_posix(), p.read_bytes())
    try:
        shown = out.relative_to(ROOT)
    except ValueError:  # --out points outside the project
        shown = out
    print(f"  {shown}  ({out.stat().st_size / 1024:.0f} KB, {len(files) + 1} files)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gecko-id", default="media-catcher@YOUR_NAME",
                    help="unique, permanent Firefox add-on id, e.g. media-catcher@your-name")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="output folder (default: dist)")
    ap.add_argument("--allow-placeholder", action="store_true",
                    help="build even if installerUrl / gecko id still contain placeholders (testing only)")
    args = ap.parse_args()

    problems = []
    if "YOUR_GITHUB_NAME" in (EXT / "config.js").read_text(encoding="utf-8"):
        problems.append("extension/config.js: installerUrl still contains YOUR_GITHUB_NAME")
    if "YOUR_NAME" in args.gecko_id:
        problems.append("pass your own id with --gecko-id media-catcher@your-name")
    elif not re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+|\{[0-9a-fA-F-]{36}\}", args.gecko_id):
        problems.append("--gecko-id must look like name@domain (letters, digits, . _ -)")
    if problems and not args.allow_placeholder:
        print("Not building:")
        for p in problems:
            print("  -", p)
        return 1

    m = read_manifest()
    out = Path(args.out)
    print(f"Media Catcher extension {m['version']}")
    write_zip(out / f"media-catcher-chromium-{m['version']}.zip", chromium_manifest(m))
    write_zip(out / f"media-catcher-firefox-{m['version']}.zip", firefox_manifest(m, args.gecko_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
