# -*- coding: utf-8 -*-
"""Benjie updater: keeps every Benjie add-on current from the Benjie
repository, and moves a device that is still on skin.bingie over to
skin.benjie once.

New installs get everything from the repository (install repository.benjie,
then the Benjie skin, and Kodi pulls in the rest). Devices set up before the
repository existed (Benjie Setup, or IPTV Helper Fixes 1.8.0 and earlier) do
not have it, so this installs repository.benjie itself, then any Benjie add-on
that the repository has a newer version of (the forked XStream Player, TMDb
Bingie Helper and Bingie Widgets, the skin, this service), straight from the
repository's zips. It checks twice a day, and at once when the power menu's
Update runs it (RunScript(service.iptvhelperfixes,update)).

The one-time move copies Bingie's skin settings and menus (script.skinshortcuts)
to skin.benjie's names, switches the skin and answers Kodi's "keep this skin?"
with Yes. It only happens from skin.bingie, and only once. On a new install
still on Kodi's default skin it asks once whether to switch; it never switches
from any other skin someone picked."""

import json
import os
import re
import shutil
import time
import zipfile
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

REPO_URL = "https://ahmadashwah.github.io/BenjiePatches/repo/"
REPO_ADDON = "repository.benjie"
SKIN = "skin.benjie"
OLD_SKIN = "skin.bingie"
DEFAULT_SKIN = "skin.estuary"
CHECK_INTERVAL = 12 * 3600
RETRY_INTERVAL = 30 * 60

ADDON_ID = xbmcaddon.Addon().getAddonInfo("id")
HOME = xbmcvfs.translatePath("special://home/")
PROFILE = xbmcvfs.translatePath("special://profile/")
STATE_DIR = os.path.join(PROFILE, "addon_data", ADDON_ID)
STATE_FILE = os.path.join(STATE_DIR, "benjie_update.json")
MIGRATED_FLAG = os.path.join(STATE_DIR, "skin_benjie_migrated.flag")


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[IPTV Helper Fixes] {message}", level)


def _version_tuple(v):
    return tuple(int(p) for p in re.findall(r"\d+", v or ""))


def _rpc(method, **params):
    return json.loads(xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})))


def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def installed_version(addon_id):
    try:
        return ET.parse(os.path.join(HOME, "addons", addon_id, "addon.xml")).getroot().get("version", "")
    except Exception:
        return ""


def _fetch(url):
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def repo_addons():
    """{id: (version, [ids of Benjie add-ons it needs])} from the repository."""
    root = ET.fromstring(_fetch(REPO_URL + "addons.xml"))
    ids = {a.get("id") for a in root.findall("addon")}
    return {
        a.get("id"): (a.get("version"), [i.get("addon") for i in a.iter("import") if i.get("addon") in ids])
        for a in root.findall("addon")
    }


def _order(wanted, listing):
    """Dependencies before what needs them; this service last, since its new
    code only runs after a restart anyway."""
    ordered, seen = [], set()

    def visit(a):
        if a in seen:
            return
        seen.add(a)
        for d in listing[a][1]:
            if d in wanted:
                visit(d)
        ordered.append(a)

    for a in sorted(wanted):
        visit(a)
    if ADDON_ID in ordered:
        ordered.remove(ADDON_ID)
        ordered.append(ADDON_ID)
    return ordered


def _install(addon_id, version):
    """Unpacks <id>/ from the repository's zip into special://home/addons."""
    tmp = os.path.join(xbmcvfs.translatePath("special://temp/"), f"benjie_{addon_id}.zip")
    dest_root = os.path.realpath(os.path.join(HOME, "addons"))
    try:
        with open(tmp, "wb") as f:
            f.write(_fetch(f"{REPO_URL}{addon_id}/{addon_id}-{version}.zip"))
        with zipfile.ZipFile(tmp) as z:
            names = z.namelist()
            if f"{addon_id}/addon.xml" not in names:
                raise RuntimeError(f"{addon_id}: the download is not the expected package")
            root = ET.fromstring(z.read(f"{addon_id}/addon.xml"))
            if root.get("id") != addon_id:
                raise RuntimeError(f"{addon_id}: the download is a different add-on")
            for name in names:
                if name.endswith("/") or not name.startswith(addon_id + "/") or "__pycache__" in name:
                    continue
                target = os.path.realpath(os.path.join(dest_root, name))
                if not target.startswith(dest_root + os.sep):
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(name) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _register_and_enable(addon_ids, monitor):
    xbmc.executebuiltin("UpdateLocalAddons")
    end = time.time() + 30
    while time.time() < end and not all(xbmc.getCondVisibility(f"System.HasAddon({a})") for a in addon_ids):
        if monitor.waitForAbort(1):
            return
    for a in addon_ids:
        if not xbmc.getCondVisibility(f"System.AddonIsEnabled({a})"):
            res = _rpc("Addons.SetAddonEnabled", addonid=a, enabled=True)
            if "error" in res:
                log(f"Benjie update: could not enable {a}: {res['error'].get('message')}", xbmc.LOGWARNING)


def update_all(monitor, force=False, progress=None):
    """Installs the repository if missing and every Benjie add-on that is
    out of date (plus skin.benjie on a device still on Bingie). Returns the
    list of (id, old version, new version) installed, or None when skipped
    or the repository could not be read."""
    state = _load_state()
    if not force:
        wait = CHECK_INTERVAL if installed_version(SKIN) else RETRY_INTERVAL
        if time.time() - state.get("last_check", 0) < wait:
            return None
    state["last_check"] = time.time()
    _save_state(state)
    try:
        listing = repo_addons()
    except Exception as e:
        log(f"Benjie update: could not read the Benjie repository: {e}", xbmc.LOGWARNING)
        if force:
            raise
        return None

    wanted = set()
    for a, (version, _) in listing.items():
        local = installed_version(a)
        if local and _version_tuple(version) > _version_tuple(local):
            wanted.add(a)
    for a in (REPO_ADDON,) + ((SKIN,) if xbmc.getSkinDir() == OLD_SKIN else ()):
        if a in listing and not installed_version(a):
            wanted.add(a)
            wanted.update(d for d in listing[a][1] if not installed_version(d))

    done = []
    order = _order(wanted, listing)
    for i, a in enumerate(order):
        if progress:
            progress.update(int(10 + 80 * i / max(1, len(order))), f"Installing {a} {listing[a][0]}...")
        old = installed_version(a)
        try:
            _install(a, listing[a][0])
            done.append((a, old, listing[a][0]))
            log(f"Benjie update: {a} {old or '(new)'} -> {listing[a][0]}")
        except Exception as e:
            log(f"Benjie update: {a} failed: {e}", xbmc.LOGWARNING)
    if done:
        _register_and_enable([a for a, _, _ in done], monitor)
    return done


def _copy_file(s, d):
    os.makedirs(os.path.dirname(d), exist_ok=True)
    if s.endswith((".xml", ".properties")):
        with open(s, "r", encoding="utf-8", errors="surrogateescape") as f:
            text = f.read()
        with open(d, "w", encoding="utf-8", errors="surrogateescape") as f:
            f.write(text.replace(OLD_SKIN, SKIN))
    else:
        shutil.copyfile(s, d)


def copy_skin_data(profile=PROFILE):
    """addon_data/skin.bingie -> addon_data/skin.benjie, and
    script.skinshortcuts' skin.bingie-*.DATA.xml / skin.bingie.properties ->
    skin.benjie names (skin.bingie in the text changed too). Not the .hash
    files, so skinshortcuts rebuilds the menu for the new skin. Overwrites:
    skin.benjie has never been used on a device that is still on skin.bingie."""
    data = os.path.join(profile, "addon_data")
    n = 0
    old = os.path.join(data, OLD_SKIN)
    for dp, _, fns in os.walk(old):
        for fn in fns:
            s = os.path.join(dp, fn)
            _copy_file(s, os.path.join(data, SKIN, os.path.relpath(s, old)))
            n += 1
    sk = os.path.join(data, "script.skinshortcuts")
    if os.path.isdir(sk):
        for fn in os.listdir(sk):
            if (fn.startswith(OLD_SKIN + "-") and fn.endswith(".DATA.xml")) or fn == OLD_SKIN + ".properties":
                _copy_file(os.path.join(sk, fn), os.path.join(sk, SKIN + fn[len(OLD_SKIN):]))
                n += 1
    return n


def _safe_to_switch():
    return (
        xbmc.getCondVisibility("Window.IsActive(home)")
        and not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)")
        and not xbmc.getCondVisibility("System.HasActiveModalDialog")
    )


def switch_skin(monitor):
    _rpc("Settings.SetSettingValue", setting="lookandfeel.skin", value=SKIN)
    # Kodi asks "keep this skin?" for a few seconds, then reverts; say Yes.
    end = time.time() + 20
    while time.time() < end:
        if xbmc.getCondVisibility("Window.IsActive(yesnodialog)"):
            monitor.waitForAbort(0.5)
            xbmc.executebuiltin("SendClick(11)")
            break
        if monitor.waitForAbort(0.5):
            return False
    monitor.waitForAbort(3)
    return xbmc.getSkinDir() == SKIN


def _mark_migrated(why):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(MIGRATED_FLAG, "w") as f:
        f.write(why)


def switch_pending():
    """True while migrate_once still has a skin switch to make or offer."""
    return (
        not os.path.isfile(MIGRATED_FLAG)
        and xbmc.getSkinDir() in (OLD_SKIN, DEFAULT_SKIN)
        and xbmc.getCondVisibility(f"System.AddonIsEnabled({SKIN})")
    )


def migrate_once(monitor):
    """Moves a device from skin.bingie to skin.benjie, once. On a new install
    (skin.benjie installed from the repository while Kodi is still on its
    default skin) it asks once instead, since Kodi does not always offer to
    switch after installing a skin."""
    if os.path.isfile(MIGRATED_FLAG):
        return
    current = xbmc.getSkinDir()
    if current == SKIN:
        _mark_migrated("already on skin.benjie")
        return
    if current not in (OLD_SKIN, DEFAULT_SKIN) or not xbmc.getCondVisibility(f"System.AddonIsEnabled({SKIN})"):
        return
    if not _safe_to_switch():
        log("Benjie skin: waiting for Home (nothing playing) to switch skins.")
        return
    if current == DEFAULT_SKIN:
        import xbmcgui

        if not xbmcgui.Dialog().yesno("Benjie", "Switch to the Benjie skin now?", yeslabel="Switch", nolabel="Not now"):
            _mark_migrated("declined on the default skin")
            log("Benjie skin: switching from the default skin declined; not asking again.")
            return
        if switch_skin(monitor):
            _mark_migrated("switched from the default skin")
            log("Benjie skin: switched from the default skin.")
        return
    n = copy_skin_data()
    log(f"Benjie skin: copied {n} Bingie settings/menu files to skin.benjie.")
    if switch_skin(monitor):
        _mark_migrated("switched from skin.bingie")
        log("Benjie skin: switched from Bingie to Benjie.")
    else:
        log("Benjie skin: the skin switch did not stick; will try again.", xbmc.LOGWARNING)


def run(monitor):
    """Background pass from the service."""
    done = update_all(monitor)
    if done and any(a == SKIN for a, _, _ in done) and xbmc.getSkinDir() == SKIN \
            and not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        xbmc.executebuiltin("ReloadSkin()")
    migrate_once(monitor)


def run_interactive():
    """The power menu's Update: checks now and says what happened."""
    import xbmcgui

    dialog = xbmcgui.Dialog()
    progress = xbmcgui.DialogProgress()
    progress.create("Update", "Checking the Benjie repository...")
    try:
        done = update_all(xbmc.Monitor(), force=True, progress=progress)
    except Exception as e:
        progress.close()
        dialog.ok("Update", f"The update did not work: {e}[CR]Check the internet connection and try again.")
        return
    progress.close()
    if not done:
        dialog.ok("Update", "Everything is up to date.")
        return
    lines = "[CR]".join(f"{a} {new}" for a, _, new in done)
    if dialog.yesno("Update", f"Updated:[CR]{lines}[CR]Restart Kodi now to finish?"):
        xbmc.executebuiltin("Quit()")
