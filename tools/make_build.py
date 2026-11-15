#!/usr/bin/env python3
"""Builds the Benjie repository that GitHub Pages serves.

    python3 tools/make_build.py                 # release: bump versions, repo/ + root zips
    python3 tools/make_build.py --check         # only show what a release would bump
    python3 tools/make_build.py --test-url http://127.0.0.1:8099/repo/ --out /tmp/benjie-test

One version: a release run bumps every Benjie add-on whose files changed since
the last release (last number +1, unless you already raised it by hand), bumps
the skin whenever anything changed, and sets the skin's requirements to the
current version of every Benjie add-on. Updating the skin therefore brings
everything else to the same release. The last release is recorded in
repo/benjie-release.json. Changelogs (<news>) are still yours to write.

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


# ------------------------------------------------------------ one version
#
# The skin is the one version that matters: whenever any Benjie add-on
# changed since the last release, that add-on's version is bumped, the skin
# is bumped too, and the skin's requirements are set to the current version
# of every Benjie add-on. Updating the skin therefore always brings everything
# else up to the same release. What was released is recorded (a fingerprint of
# each add-on's files) in repo/benjie-release.json.

SKIN = "skin.benjie"
STATE_FILE = os.path.join(REPO, "repo", "benjie-release.json")
# Benjie add-ons the skin requires (everything hosted except the repository add-on).
SKIN_REQUIRES = [a for a in HOSTED if a not in ("repository.benjie", SKIN)]


def _addon_tag_re():
    return re.compile(r'(<addon\b[^>]*?\bversion=")([^"]*)(")', re.S)


def read_version(addon_id):
    return ET.parse(os.path.join(REPO, addon_id, "addon.xml")).getroot().get("version")


def normalized_addon_xml(addon_id, text):
    """addon.xml with the parts this script manages blanked out, so changing
    them does not count as a change: the add-on's own version and, in the
    skin, the versions it requires of the other Benjie add-ons."""
    text = _addon_tag_re().sub(r"\1\3", text, count=1)
    if addon_id == SKIN:
        for dep in SKIN_REQUIRES:
            text = re.sub(r'(<import\b[^>]*\baddon="%s"[^>]*?\bversion=")[^"]*(")' % re.escape(dep), r"\1\2", text)
    return text


def fingerprint(addon_id):
    src = os.path.join(REPO, addon_id)
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(src):
        dns[:] = sorted(d for d in dns if want(d))
        for fn in sorted(fns):
            if not want(fn):
                continue
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, src).replace(os.sep, "/")
            data = open(full, "rb").read()
            if rel == "addon.xml":
                data = normalized_addon_xml(addon_id, data.decode("utf-8")).encode("utf-8")
            data = data.replace(b"\r\n", b"\n")
            h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def bumped(version):
    """1.9.0 -> 1.9.1, 2.0.2.2 -> 2.0.2.3."""
    parts = version.split(".")
    for i in range(len(parts) - 1, -1, -1):
        m = re.fullmatch(r"(\d+)(.*)", parts[i])
        if m:
            parts[i] = str(int(m.group(1)) + 1)
            break
    return ".".join(parts)


def write_addon_xml(addon_id, edit):
    p = os.path.join(REPO, addon_id, "addon.xml")
    with open(p, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = edit(raw.decode("utf-8-sig"))
    ET.fromstring(text.encode("utf-8"))  # must still parse
    with open(p, "wb") as f:
        f.write((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def set_version(addon_id, version):
    write_addon_xml(addon_id, lambda t: _addon_tag_re().sub(lambda m: m.group(1) + version + m.group(3), t, count=1))


def set_skin_requirements(versions, add_missing):
    """Sets the skin's required versions of the Benjie add-ons. Requirements
    the skin does not list yet are only added when the skin itself is being
    bumped, so a released skin version never changes without a new number."""
    def edit(text):
        for dep in SKIN_REQUIRES:
            pat = re.compile(r'(<import\b[^>]*\baddon="%s"[^>]*?\bversion=")[^"]*(")' % re.escape(dep))
            if pat.search(text):
                text = pat.sub(lambda m: m.group(1) + versions[dep] + m.group(2), text)
            elif add_missing:
                text = text.replace("</requires>", f'\t<import addon="{dep}" version="{versions[dep]}" />\n\t</requires>', 1)
                print(f"  skin now requires {dep} {versions[dep]}")
        return text

    write_addon_xml(SKIN, edit)


def sync_versions(dry_run=False):
    """Bumps what changed since the last release and ties the skin to the
    current version of everything. Returns {id: version} after the bump."""
    import json

    state = {}
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    versions = {a: read_version(a) for a in HOSTED}
    prints = {a: fingerprint(a) for a in HOSTED}
    if not state:
        print("No release recorded yet: recording the current add-ons as the baseline (no bumps).")
        changed = []
    else:
        changed = [a for a in HOSTED if state.get(a, {}).get("fingerprint") != prints[a]]
    bumps = {}
    for a in changed:
        released = state.get(a, {}).get("version")
        # Bump unless the version was already raised by hand since the release.
        if released and versions[a] == released:
            bumps[a] = bumped(versions[a])
    skin_needs_bump = bool(changed) and SKIN not in bumps and versions[SKIN] == state.get(SKIN, {}).get("version")
    if skin_needs_bump:
        bumps[SKIN] = bumped(versions[SKIN])
    for a, v in bumps.items():
        print(f"  bump {a}: {versions[a]} -> {v}")
    if changed and not bumps:
        print("  changed, versions already raised by hand:", ", ".join(changed))
    if not changed and state:
        print("  nothing changed since the last release")
    versions.update(bumps)
    if dry_run:
        return versions
    for a, v in bumps.items():
        if a != SKIN:
            set_version(a, v)
    if SKIN in bumps:
        set_version(SKIN, bumps[SKIN])
    set_skin_requirements(versions, add_missing=SKIN in bumps)
    # Record what is being released (fingerprints after the edits above).
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    record = {a: {"version": read_version(a), "fingerprint": fingerprint(a)} for a in HOSTED}
    with open(STATE_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=1, sort_keys=True)
        f.write("\n")
    return {a: record[a]["version"] for a in HOSTED}


def addon_xml_text(addon_id, repo_url):
    text = open(os.path.join(REPO, addon_id, "addon.xml"), encoding="utf-8").read()
    if addon_id == "repository.benjie" and repo_url != PAGES_URL:
        text = text.replace(PAGES_URL, repo_url)
    return text


def zip_addon(addon_id, out_zip, repo_url):
    """Reproducible zip: fixed timestamps and permissions, sorted entries, so
    an add-on whose files did not change gives a byte-identical zip (no
    repository churn for add-ons a release did not touch)."""
    src = os.path.join(REPO, addon_id)

    def put(z, arc, data):
        info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        info.create_system = 3
        z.writestr(info, data, compresslevel=6)

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, dns, fns in os.walk(src):
            dns[:] = sorted(d for d in dns if want(d))
            for fn in sorted(fns):
                if not want(fn):
                    continue
                full = os.path.join(dp, fn)
                arc = addon_id + "/" + os.path.relpath(full, src).replace(os.sep, "/")
                if arc == f"{addon_id}/addon.xml":
                    put(z, arc, addon_xml_text(addon_id, repo_url).encode("utf-8"))
                else:
                    with open(full, "rb") as f:
                        put(z, arc, f.read())


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
    ap.add_argument("--check", action="store_true", help="only show which versions a release would bump")
    args = ap.parse_args()
    repo_url = args.test_url or PAGES_URL
    if not repo_url.endswith("/"):
        repo_url += "/"
    base = args.out or REPO
    if args.test_url and not args.out:
        sys.exit("--test-url needs --out, so the published repository is not changed")
    if args.check:
        sync_versions(dry_run=True)
        return
    if args.test_url:
        # A test build uses the versions as they are; only a release bumps them.
        print("Test build: versions as they are (a release run bumps them).")
    else:
        print("Versions:")
        sync_versions()
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
