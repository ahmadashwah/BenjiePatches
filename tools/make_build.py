#!/usr/bin/env python3
"""Builds the Benjie repository that GitHub Pages serves.

    python3 tools/make_build.py                 # repo/ + the release zips in the repo root
    python3 tools/make_build.py --test-url http://127.0.0.1:8099/repo/ --out /tmp/benjie-test

Every add-on Benjie hosts lives in this repo as source (the skin, the forked
XStream Player / TMDb Bingie Helper / Bingie Widgets, the Bingie helper
scripts, IPTV Helper Fixes and the repository add-on itself). This zips each
one into repo/<id>/<id>-<version>.zip (the layout Kodi's repository add-ons
read, with the icon/fanart next to it), writes repo/addons.xml and its .md5,
and drops older versions. Everything else the skin needs comes from Kodi's
own repository.

In the repo root it also writes:
  repository.benjie-<ver>.zip      what people install from zip (then the skin from it)
  service.iptvhelperfixes<ver>.zip what the power menu's Update on older devices downloads
  skin.benjie-<ver>.zip            what IPTV Helper Fixes 1.8.0 downloads for skin updates

--test-url builds the same into --out with the repository add-on pointing at
another address (a local web server for testing); the repo is not touched.
"""
import argparse
import glob
import hashlib
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_URL = "https://ahmadashwah.github.io/BenjiePatches/repo/"
HOSTED = [
    "repository.benjie",
    "skin.benjie",
    "service.iptvhelperfixes",
    "plugin.video.xstream-player",
    "plugin.video.tmdb.bingie.helper",
    "script.bingie.widgets",
    "script.bingie.helper",
    "script.bingie.toolbox",
    "script.module.bingie",
]
SKIP_NAMES = {"__pycache__", ".git", ".DS_Store"}
SKIP_SUFFIXES = (".pyc", ".pyo")
SKIP_CONTAINS = (".bak-", ".bak.", "addon.py.bak")


def want(name):
    return name not in SKIP_NAMES and not name.endswith(SKIP_SUFFIXES) and not any(s in name for s in SKIP_CONTAINS)


def addon_xml_text(addon_id, repo_url):
    text = open(os.path.join(REPO, addon_id, "addon.xml"), encoding="utf-8").read()
    if addon_id == "repository.benjie" and repo_url != PAGES_URL:
        text = text.replace(PAGES_URL, repo_url)
    return text


def zip_addon(addon_id, out_zip, repo_url):
    src = os.path.join(REPO, addon_id)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, dns, fns in os.walk(src):
            dns[:] = sorted(d for d in dns if want(d))
            for fn in sorted(fns):
                if not want(fn):
                    continue
                full = os.path.join(dp, fn)
                arc = addon_id + "/" + os.path.relpath(full, src).replace(os.sep, "/")
                if arc == f"{addon_id}/addon.xml":
                    z.writestr(arc, addon_xml_text(addon_id, repo_url))
                else:
                    z.write(full, arc)


def assets(root):
    """Icon/fanart/screenshot paths the add-on declares (or the legacy names)."""
    meta = next((e for e in root.findall("extension") if e.get("point") == "xbmc.addon.metadata"), None)
    found = []
    if meta is not None and meta.find("assets") is not None:
        found = [e.text.strip() for e in meta.find("assets") if e.text and e.text.strip()]
    for legacy in ("icon.png", "fanart.jpg"):
        if legacy not in found:
            found.append(legacy)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-url", help="repository address to build for instead of GitHub Pages")
    ap.add_argument("--out", help="output folder (default: this repo)")
    args = ap.parse_args()
    repo_url = args.test_url or PAGES_URL
    if not repo_url.endswith("/"):
        repo_url += "/"
    base = args.out or REPO
    if args.test_url and not args.out:
        sys.exit("--test-url needs --out, so the published repository is not changed")
    repo_dir = os.path.join(base, "repo")
    os.makedirs(repo_dir, exist_ok=True)

    entries, versions = [], {}
    for a in HOSTED:
        text = addon_xml_text(a, repo_url)
        root = ET.fromstring(text.encode("utf-8"))
        if root.get("id") != a:
            sys.exit(f"{a}/addon.xml has id {root.get('id')}")
        version = root.get("version")
        versions[a] = version
        d = os.path.join(repo_dir, a)
        os.makedirs(d, exist_ok=True)
        target = os.path.join(d, f"{a}-{version}.zip")
        for old in glob.glob(os.path.join(d, f"{a}-*.zip")) + glob.glob(os.path.join(d, f"{a}-*.zip.md5")):
            if os.path.basename(old) not in (os.path.basename(target), os.path.basename(target) + ".md5"):
                os.remove(old)
        zip_addon(a, target, repo_url)
        with open(target, "rb") as f:
            md5 = hashlib.md5(f.read()).hexdigest()
        with open(target + ".md5", "w") as f:
            f.write(md5)
        for rel in assets(root):
            src = os.path.join(REPO, a, rel)
            if os.path.isfile(src):
                dst = os.path.join(d, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(src, "rb") as s, open(dst, "wb") as o:
                    o.write(s.read())
        text = text.lstrip(chr(0xFEFF))  # some add-ons start with a byte-order mark
        entries.append(re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text).strip())
        print(f"  {a} {version} ({os.path.getsize(target) / 1e6:.1f} MB)")

    addons_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n' + "\n".join(entries) + "\n</addons>\n"
    ET.fromstring(addons_xml.encode("utf-8"))  # must parse
    with open(os.path.join(repo_dir, "addons.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(addons_xml)
    with open(os.path.join(repo_dir, "addons.xml.md5"), "w") as f:
        f.write(hashlib.md5(addons_xml.encode("utf-8")).hexdigest())

    # Release zips in the root of the output (the Pages site's top level).
    root_zips = {
        "repository.benjie": f"repository.benjie-{versions['repository.benjie']}.zip",
        "service.iptvhelperfixes": f"service.iptvhelperfixes{versions['service.iptvhelperfixes'].replace('.', '')}.zip",
        "skin.benjie": f"skin.benjie-{versions['skin.benjie']}.zip",
    }
    patterns = {
        "repository.benjie": r"repository\.benjie-[\d.]+\.zip",
        "service.iptvhelperfixes": r"service\.iptvhelperfixes\d+\.zip",
        "skin.benjie": r"skin\.benjie-[\d.]+\.zip",
    }
    for a, name in root_zips.items():
        for old in os.listdir(base):
            if re.fullmatch(patterns[a], old) and old != name:
                os.remove(os.path.join(base, old))
        zip_addon(a, os.path.join(base, name), repo_url)
        print(f"  root: {name}")
    print(f"\nRepository written to {repo_dir} for {repo_url}")


if __name__ == "__main__":
    main()
