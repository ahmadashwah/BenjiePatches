# -*- coding: utf-8 -*-
"""Bengie updater: keeps every Bengie add-on current from the Bengie
repository, and moves a device that is still on skin.bingie over to
skin.benjie once.

New installs get everything from the repository (install repository.benjie,
then the Bengie skin, and Kodi pulls in the rest). Devices set up before the
repository existed (Bengie Setup, or IPTV Helper Fixes 1.8.0 and earlier) do
not have it, so this installs repository.benjie itself, then any Bengie add-on
that the repository has a newer version of (the forked XStream Player, TMDb
Bingie Helper and Bingie Widgets, the skin, this service), straight from the
repository's zips. It checks twice a day (leaving it to Kodi where the
repository is installed and Kodi installs updates automatically), and at once
when the power menu's Update runs it (connect.py with "update").

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

ADDON_ID = xbmcaddon.Addon("service.iptvhelperfixes").getAddonInfo("id")
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
    """{id: (version, [ids of Bengie add-ons it needs])} from the repository."""
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


def _make_replaceable(path):
    """Windows refuses to open a hidden or read-only file for writing ("Permission
    denied"); Kodi marks files whose names start with a dot hidden when it
    installs a zip, so the skin's .gitattributes made every update of it fail.
    Deleting the old file first works for both."""
    if not os.path.lexists(path):
        return
    try:
        os.chmod(path, 0o666)
    except OSError:
        pass
    try:
        os.remove(path)
    except OSError:
        pass


LOCK_FILE = os.path.join(STATE_DIR, "benjie_update.lock")
LOCK_STALE = 15 * 60


def _take_lock():
    """One update run at a time, across Kodi's Python interpreters (a service
    restarted by an add-on update used to start a second run beside the first,
    downloading the same 27 MB skin twice). A lock older than 15 minutes is a
    leftover from a run that never finished."""
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        if time.time() - os.path.getmtime(LOCK_FILE) < LOCK_STALE:
            return False
        os.remove(LOCK_FILE)
    except OSError:
        pass
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        return False


def _release_lock():
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


def kodi_updates_automatically():
    """True when Kodi itself installs add-on updates (Settings > System >
    Add-ons > Updates: "Install updates automatically", the default)."""
    res = _rpc("Settings.GetSettingValue", setting="general.addonupdates")
    return (res.get("result") or {}).get("value") == 0


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
                if os.path.basename(name).startswith(".git"):
                    continue  # repository files, not part of the add-on
                target = os.path.realpath(os.path.join(dest_root, name))
                if not target.startswith(dest_root + os.sep):
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                _make_replaceable(target)
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
                log(f"Bengie update: could not enable {a}: {res['error'].get('message')}", xbmc.LOGWARNING)


def update_all(monitor, force=False, progress=None):
    """Installs the repository if missing and every Bengie add-on that is
    out of date (plus skin.benjie on a device still on Bingie). Returns the
    list of (id, old version, new version) installed, or None when skipped
    or the repository could not be read.

    The background check (not force) leaves a device that has the Bengie
    repository and Kodi's automatic add-on updates on to Kodi: Kodi installs
    the same updates itself, and two installers at once (at every start after
    a release) downloaded everything twice and tripped over each other. Only
    devices without the repository (set up before it existed), still on
    Bingie, or with automatic updates off are updated from here. The power
    menu's Update (force) always runs."""
    state = _load_state()
    if not force:
        wait = CHECK_INTERVAL if installed_version(SKIN) else RETRY_INTERVAL
        if time.time() - state.get("last_check", 0) < wait:
            return None
        if installed_version(REPO_ADDON) and xbmc.getSkinDir() != OLD_SKIN and kodi_updates_automatically():
            log("Bengie update: Kodi installs Bengie updates itself (repository installed, automatic updates on).")
            return None
    if not _take_lock():
        log("Bengie update: another update is already running.")
        if force:
            raise RuntimeError("another update is already running")
        return None
    try:
        return _update_all_locked(monitor, force, progress, state)
    finally:
        _release_lock()


def _update_all_locked(monitor, force, progress, state):
    state["last_check"] = time.time()
    _save_state(state)
    try:
        listing = repo_addons()
    except Exception as e:
        log(f"Bengie update: could not read the Bengie repository: {e}", xbmc.LOGWARNING)
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
    # Bengie add-ons an update newly needs and that aren't installed yet (the
    # skin needs script.benjie.bundle from skin 2.0.2.9 on, and the bundle
    # needs the rest), followed all the way down.
    # Also what an installed add-on already needs but is missing (a device
    # that got such an update from an older updater repairs itself).
    todo = list(wanted) + [a for a in listing if installed_version(a)]
    while todo:
        for d in listing.get(todo.pop(), (None, []))[1]:
            if d in listing and d not in wanted and not installed_version(d):
                wanted.add(d)
                todo.append(d)

    done = []
    order = _order(wanted, listing)
    for i, a in enumerate(order):
        if progress:
            progress.update(int(10 + 80 * i / max(1, len(order))), f"Installing {a} {listing[a][0]}...")
        old = installed_version(a)
        try:
            _install(a, listing[a][0])
            done.append((a, old, listing[a][0]))
            log(f"Bengie update: {a} {old or '(new)'} -> {listing[a][0]}")
        except Exception as e:
            log(f"Bengie update: {a} failed: {e}", xbmc.LOGWARNING)
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
        log("Bengie skin: waiting for Home (nothing playing) to switch skins.")
        return
    if current == DEFAULT_SKIN:
        import xbmcgui

        if not xbmcgui.Dialog().yesno("Bengie", "Switch to the Bengie skin now?", yeslabel="Switch", nolabel="Not now"):
            _mark_migrated("declined on the default skin")
            log("Bengie skin: switching from the default skin declined; not asking again.")
            return
        if switch_skin(monitor):
            _mark_migrated("switched from the default skin")
            log("Bengie skin: switched from the default skin.")
        return
    n = copy_skin_data()
    log(f"Bengie skin: copied {n} Bingie settings/menu files to skin.benjie.")
    if switch_skin(monitor):
        _mark_migrated("switched from skin.bingie")
        log("Bengie skin: switched from Bingie to Bengie.")
    else:
        log("Bengie skin: the skin switch did not stick; will try again.", xbmc.LOGWARNING)


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
    progress.create("Update", "Checking the Bengie repository...")
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
