# -*- coding: utf-8 -*-
"""Benjie skin: installs and updates skin.benjie (Bingie with this add-on's
skin changes built in) from the GitHub repo, and moves a device that is still
on skin.bingie over to it once.

The power menu's Update only installs this add-on, so the skin comes from here:
the newest skin.benjie-<version>.zip in the repo (found through GitHub's file
listing, like the Update itself) is downloaded when skin.benjie is missing or
older. The one-time move copies Bingie's skin settings and the menu
(script.skinshortcuts) files to skin.benjie's names, then switches the skin and
answers Kodi's "keep this skin?" with Yes. It only happens from skin.bingie,
never from another skin someone picked, and only once."""

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

SKIN = "skin.benjie"
OLD_SKIN = "skin.bingie"
REPO_API = "https://api.github.com/repos/ahmadashwah/BenjiePatches/contents/"
CHECK_INTERVAL = 12 * 3600
RETRY_INTERVAL = 30 * 60

ADDON_ID = xbmcaddon.Addon().getAddonInfo("id")
HOME = xbmcvfs.translatePath("special://home/")
PROFILE = xbmcvfs.translatePath("special://profile/")
STATE_DIR = os.path.join(PROFILE, "addon_data", ADDON_ID)
STATE_FILE = os.path.join(STATE_DIR, "skin_benjie.json")
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


def installed_version():
    try:
        return ET.parse(os.path.join(HOME, "addons", SKIN, "addon.xml")).getroot().get("version", "")
    except Exception:
        return ""


def _fetch(url):
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _newest_in_repo():
    listing = json.loads(_fetch(REPO_API).decode("utf-8", "replace"))
    best = None
    for f in listing:
        m = re.fullmatch(r"skin\.benjie-(\d+(?:\.\d+)*)\.zip", f.get("name", ""))
        if m and f.get("download_url"):
            if best is None or _version_tuple(m.group(1)) > _version_tuple(best[0]):
                best = (m.group(1), f["download_url"])
    return best


def _install_zip(path):
    """Unpacks skin.benjie/ from the zip into special://home/addons. Returns
    the version in the zip's addon.xml."""
    dest_root = os.path.realpath(os.path.join(HOME, "addons"))
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if f"{SKIN}/addon.xml" not in names:
            raise RuntimeError("the download is not the expected package")
        root = ET.fromstring(z.read(f"{SKIN}/addon.xml"))
        if root.get("id") != SKIN:
            raise RuntimeError("the download is not skin.benjie")
        version = root.get("version", "")
        for name in names:
            if name.endswith("/") or not name.startswith(SKIN + "/"):
                continue
            target = os.path.realpath(os.path.join(dest_root, name))
            if not target.startswith(dest_root + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(name) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return version


def _register_and_enable(monitor):
    xbmc.executebuiltin("UpdateLocalAddons")
    end = time.time() + 30
    while time.time() < end and not xbmc.getCondVisibility(f"System.HasAddon({SKIN})"):
        if monitor.waitForAbort(1):
            return False
    if not xbmc.getCondVisibility(f"System.AddonIsEnabled({SKIN})"):
        res = _rpc("Addons.SetAddonEnabled", addonid=SKIN, enabled=True)
        if "error" in res:
            log(f"could not enable {SKIN}: {res['error'].get('message')}", xbmc.LOGWARNING)
    return xbmc.getCondVisibility(f"System.HasAddon({SKIN})")


def ensure_installed(monitor):
    """Installs skin.benjie, or updates it when the repo has a newer one.
    Checks GitHub at most every 12 hours (every 30 minutes while the skin is
    missing). Returns True when the installed skin changed."""
    state = _load_state()
    local = installed_version()
    wait = CHECK_INTERVAL if local else RETRY_INTERVAL
    if time.time() - state.get("last_check", 0) < wait:
        return False
    state["last_check"] = time.time()
    _save_state(state)
    try:
        newest = _newest_in_repo()
    except Exception as e:
        log(f"Benjie skin: could not check GitHub: {e}", xbmc.LOGWARNING)
        return False
    if not newest:
        log("Benjie skin: no skin.benjie zip in the repo.", xbmc.LOGWARNING)
        return False
    remote, url = newest
    if local and _version_tuple(remote) <= _version_tuple(local):
        return False
    tmp = os.path.join(xbmcvfs.translatePath("special://temp/"), "skin.benjie_update.zip")
    try:
        log(f"Benjie skin: downloading {remote} (installed: {local or 'none'}).")
        with open(tmp, "wb") as f:
            f.write(_fetch(url))
        version = _install_zip(tmp)
    except Exception as e:
        log(f"Benjie skin: install failed: {e}", xbmc.LOGWARNING)
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    ok = _register_and_enable(monitor)
    log(f"Benjie skin {version} installed{'' if ok else ', but Kodi has not registered it yet'}.")
    return ok


def _copy_tree(src, dst):
    """Copies src into dst, overwriting, with skin.bingie in XML text changed
    to skin.benjie (skinshortcuts writes the skin id into some entries, and
    custom image paths point into addon_data/skin.bingie)."""
    copied = 0
    for dp, _, fns in os.walk(src):
        for fn in fns:
            s = os.path.join(dp, fn)
            d = os.path.join(dst, os.path.relpath(s, src))
            _copy_file(s, d)
            copied += 1
    return copied


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
    skin.benjie names. Not the .hash files, so skinshortcuts rebuilds the
    menu for the new skin. Overwrites: skin.benjie has never been used on a
    device that is still on skin.bingie."""
    data = os.path.join(profile, "addon_data")
    n = 0
    old = os.path.join(data, OLD_SKIN)
    if os.path.isdir(old):
        n += _copy_tree(old, os.path.join(data, SKIN))
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


def migrate_once(monitor):
    """Moves a device from skin.bingie to skin.benjie, once."""
    if os.path.isfile(MIGRATED_FLAG):
        return
    current = xbmc.getSkinDir()
    if current == SKIN:
        _mark_migrated("already on skin.benjie")
        return
    if current != OLD_SKIN or not xbmc.getCondVisibility(f"System.AddonIsEnabled({SKIN})"):
        return
    if not _safe_to_switch():
        log("Benjie skin: waiting for Home (nothing playing) to switch skins.")
        return
    n = copy_skin_data()
    log(f"Benjie skin: copied {n} Bingie settings/menu files to skin.benjie.")
    if switch_skin(monitor):
        _mark_migrated("switched from skin.bingie")
        log("Benjie skin: switched from Bingie to Benjie.")
    else:
        log("Benjie skin: the skin switch did not stick; will try again.", xbmc.LOGWARNING)


def _mark_migrated(why):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(MIGRATED_FLAG, "w") as f:
        f.write(why)


def run(monitor):
    changed = ensure_installed(monitor)
    if changed and xbmc.getSkinDir() == SKIN and not xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        xbmc.executebuiltin("ReloadSkin()")
    migrate_once(monitor)
