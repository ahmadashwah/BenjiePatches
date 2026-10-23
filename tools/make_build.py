#!/usr/bin/env python3
"""Build a clean, shareable "build" zip of this Kodi setup.

    python3 tools/make_build.py [--out DIR] [--kodi-home DIR]

The zip unpacks into Kodi's data folder (see INSTALL.txt inside it) and gives
a fresh install: Bingie skin and every add-on it needs, the IPTV Helper Fixes
service (from this repo, not the live copy), keymaps, skin settings and the
Home / New & Popular layout. Personal data is left out: IPTV login, profile
names, watch history and favourites, caches, thumbnails, databases, Trakt and
other account tokens, and the owner's GitHub sync token.

Error reports: set BENJIE_DIAG_TOKEN to a GitHub token with the gist scope,
ideally from a separate account made only for this, and the build reports into
that account's gist (read them with tools/read_diagnostics.py). Anyone who
unzips the build can read that token, so never use a personal one. Without it
the build still works, and error reports stay on the device.

API keys for ratings (OMDb for IMDb, MDBList, fanart.tv) that are set in TMDb
Bingie Helper are kept.
"""
import argparse
import datetime
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_HOME = os.path.expanduser("~/Library/Application Support/Kodi")

ROOT_ADDONS = [
    "skin.bingie",
    "plugin.video.tmdb.bingie.helper",
    "plugin.video.xstream-player",
    "service.iptvhelperfixes",
    "service.subtitles.opensubtitles-com",
    "script.bingie.widgets",
]
KODI_BUILTIN_PREFIXES = ("xbmc.", "kodi.resource", "resource.language.")
# Platform-specific binaries come with Kodi or from its own repository, and
# the ones on this Mac are for this Mac only.
BINARY_PREFIXES = ("inputstream.", "pvr.", "kodi.binary.", "vfs.", "audiodecoder.", "game.", "peripheral.")
SKIP_NAMES = {"__pycache__", ".git", ".DS_Store"}
SKIP_SUFFIXES = (".pyc", ".pyo")
SKIP_CONTAINS = (".bak-", ".bak.", "addon.py.bak")


def addon_info(path):
    root = ET.parse(os.path.join(path, "addon.xml")).getroot()
    imports = [i.get("addon") for i in root.iter("import") if i.get("addon")]
    return root.get("version"), imports


def collect_addons(kodi_home):
    addons_dir = os.path.join(kodi_home, "addons")
    chosen, todo = {}, list(ROOT_ADDONS)
    while todo:
        a = todo.pop()
        if a in chosen or a.startswith(KODI_BUILTIN_PREFIXES) or a.startswith(BINARY_PREFIXES):
            continue
        path = os.path.join(addons_dir, a)
        if not os.path.isfile(os.path.join(path, "addon.xml")):
            print(f"  note: {a} is not installed here, skipping (Kodi fetches it if needed)")
            continue
        version, imports = addon_info(path)
        chosen[a] = (path, version)
        todo.extend(imports)
    # The service comes from this repo, which is the source of truth.
    repo_service = os.path.join(REPO, "service.iptvhelperfixes")
    chosen["service.iptvhelperfixes"] = (repo_service, addon_info(repo_service)[0])
    return chosen


def want_file(name):
    return name not in SKIP_NAMES and not name.endswith(SKIP_SUFFIXES) and not any(s in name for s in SKIP_CONTAINS)


def add_tree(z, src, arc_root, kodi_home):
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if want_file(d)]
        for fn in fns:
            if not want_file(fn):
                continue
            full = os.path.join(dp, fn)
            arc = os.path.join(arc_root, os.path.relpath(full, src))
            if fn == "script-skinshortcuts-includes.xml":
                # Generated file with this machine's absolute paths in it;
                # make them portable so it works wherever Kodi's data lives.
                with open(full, encoding="utf-8") as f:
                    text = f.read()
                z.writestr(arc, text.replace(os.path.join(kodi_home, "addons") + "/", "special://home/addons/"))
            else:
                z.write(full, arc)


# ---------------------------------------------------------------- userdata

def scrub_xstream_settings(text):
    """Drops every login/profile detail and machine-specific PVR id so the
    new install starts with blank profiles."""
    drop = re.compile(
        r"^(profile_\d+_(name|xtream_url|xtream_username|xtream_password|m3u|epg_.*|source_type)"
        r"|pvr_.*instance_id|last_pvr_profile|last_update_check|last_seen_version|active_pvr_profile)$"
    )

    def keep(m):
        return "" if drop.match(m.group(1)) else m.group(0)

    return re.sub(r'[ \t]*<setting id="([^"]+)"[^>]*?(?:/>|>[^<]*</setting>)\r?\n?', keep, text)


def scrub_tmdb_helper_settings(text):
    """Keeps rating API keys (OMDb, MDBList, fanart.tv); drops account
    tokens (Trakt, TMDb user, TVDb)."""
    drop = re.compile(r"^(trakt_.*|tmdb_user_token.*|tvdb_token.*)$")

    def keep(m):
        return "" if drop.match(m.group(1)) else m.group(0)

    return re.sub(r'[ \t]*<setting id="([^"]+)"[^>]*?(?:/>|>[^<]*</setting>)\r?\n?', keep, text)


def service_settings(diag_token):
    token = f'    <setting id="diag_token">{diag_token}</setting>\n' if diag_token else ""
    return (
        '<settings version="2">\n'
        '    <setting id="diag_enabled">true</setting>\n' + token + "</settings>\n"
    )


GUISETTINGS = (
    '<settings version="2">\n'
    '    <setting id="lookandfeel.skin">skin.bingie</setting>\n'
    "</settings>\n"
)


def addons_db(kodi_home, addon_ids):
    """A fresh Addons33.db marking the shipped add-ons as installed and
    enabled, with the schema copied from this Kodi's own database."""
    src = sqlite3.connect(os.path.join(kodi_home, "userdata", "Database", "Addons33.db"))
    schema = [r[0] for r in src.execute("select sql from sqlite_master where sql is not null and name not like 'sqlite_%'")]
    version_rows = src.execute("select * from version").fetchall()
    src.close()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    db = sqlite3.connect(path)
    for stmt in schema:
        db.execute(stmt)
    for row in version_rows:
        db.execute("insert into version values (%s)" % ",".join("?" * len(row)), row)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for a in sorted(addon_ids):
        db.execute(
            "insert into installed (addonID, enabled, installDate, lastUpdated, lastUsed, origin) values (?,?,?,?,?,?)",
            (a, 1, now, now, "", ""),
        )
    db.commit()
    db.close()
    return path


INSTALL_TXT = """IPTV build {stamp}

1. Install Kodi 21 (Omega) from kodi.tv or your device's app store, open it once,
   then close it completely.
2. Unzip this file into Kodi's data folder so that the "addons" and "userdata"
   folders from the zip land inside it (merge/replace if asked):
     macOS    ~/Library/Application Support/Kodi
     Windows  %APPDATA%\\Kodi
     Linux    ~/.kodi
     Android  Android/data/org.xbmc.kodi/files/.kodi   (use a file manager)
3. Start Kodi. The first start applies the setup and the second loads it, so
   close Kodi and open it again once if the look is not right yet.
4. Enter your IPTV login when asked (or tap the name at the top of the side
   menu).

Error reports (no logins or addresses) help fix problems; switch them off in
the IPTV Helper Fixes add-on settings.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "dist"))
    ap.add_argument("--kodi-home", default=DEFAULT_HOME)
    args = ap.parse_args()
    home = args.kodi_home
    ud = os.path.join(home, "userdata")
    if not os.path.isdir(os.path.join(home, "addons")):
        sys.exit(f"No Kodi data folder at {home}")

    addons = collect_addons(home)
    svc_version = addons["service.iptvhelperfixes"][1]
    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    out = os.path.join(args.out, f"iptv-build-{svc_version}.zip")
    diag_token = os.environ.get("BENJIE_DIAG_TOKEN", "").strip()

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for a, (path, version) in sorted(addons.items()):
            print(f"  addon {a} {version}")
            add_tree(z, path, f"addons/{a}", home)

        def put(arc, text):
            z.writestr(arc, text)

        put("userdata/guisettings.xml", GUISETTINGS)
        put("userdata/addon_data/service.iptvhelperfixes/settings.xml", service_settings(diag_token))
        put("INSTALL.txt", INSTALL_TXT.format(stamp=stamp))

        def read(rel):
            with open(os.path.join(ud, rel), encoding="utf-8") as f:
                return f.read()

        put("userdata/addon_data/plugin.video.xstream-player/settings.xml",
            scrub_xstream_settings(read("addon_data/plugin.video.xstream-player/settings.xml")))
        put("userdata/addon_data/plugin.video.tmdb.bingie.helper/settings.xml",
            scrub_tmdb_helper_settings(read("addon_data/plugin.video.tmdb.bingie.helper/settings.xml")))
        for rel in (
            "addon_data/skin.bingie/settings.xml",
            "keymaps/xstream_backbutton.xml",
        ):
            put(f"userdata/{rel}", read(rel))
        sk = os.path.join(ud, "addon_data", "script.skinshortcuts")
        for fn in sorted(os.listdir(sk)):
            if fn.startswith("skin.bingie") and fn.endswith(".DATA.xml"):
                put(f"userdata/addon_data/script.skinshortcuts/{fn}", read(f"addon_data/script.skinshortcuts/{fn}"))
        dbfile = addons_db(home, addons.keys())
        z.write(dbfile, "userdata/Database/Addons33.db")
        os.remove(dbfile)

    mb = os.path.getsize(out) / 1e6
    print(f"\nBuilt {out} ({mb:.0f} MB)")
    print("Error reports:", "will go to the gist of the token in BENJIE_DIAG_TOKEN" if diag_token
          else "no BENJIE_DIAG_TOKEN set, so they stay on the device")


if __name__ == "__main__":
    main()
