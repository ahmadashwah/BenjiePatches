# -*- coding: utf-8 -*-
"""Benjie Setup: unpacks the bundled build (skin, add-ons, settings) into
Kodi's data folder, enables everything and switches to the Bingie skin.

Runs once after install. Existing settings files are never overwritten, so
installing this on a device that already has a login keeps that login."""
import json
import os
import re
import time
import zipfile
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
VERSION = ADDON.getAddonInfo("version")
HERE = os.path.dirname(os.path.abspath(__file__))
PAYLOAD = os.path.join(HERE, "payload.zip")
HOME = xbmcvfs.translatePath("special://home/")
PROFILE = xbmcvfs.translatePath("special://profile/")
STATE_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
FLAG = os.path.join(STATE_DIR, f"setup_{VERSION}.done")
SKIN = "skin.bingie"
EXTRA_FROM_KODI_REPO = ["resource.images.studios.coloured"]


def log(msg):
    xbmc.log(f"[Benjie Setup] {msg}", xbmc.LOGINFO)


def rpc(method, **params):
    reply = json.loads(
        xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}))
    )
    return reply


def safe_target(root, name):
    target = os.path.realpath(os.path.join(root, name))
    return target if target.startswith(os.path.realpath(root) + os.sep) else None


def extract(progress):
    """addons/* -> special://home/addons (overwrites); userdata/* ->
    special://profile only where the file does not exist yet."""
    addon_ids = set()
    with zipfile.ZipFile(PAYLOAD) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for i, name in enumerate(names):
            if name.startswith("addons/"):
                rel = name[len("addons/"):]
                addon_ids.add(rel.split("/")[0])
                target = safe_target(os.path.join(HOME, "addons"), rel)
                overwrite = True
            elif name.startswith("userdata/"):
                rel = name[len("userdata/"):]
                target = safe_target(PROFILE, rel)
                overwrite = False
            else:
                continue
            if not target or (not overwrite and os.path.exists(target)):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                out.write(z.read(name))
            if i % 200 == 0:
                progress.update(int(75 * i / max(1, len(names))), "Copying files...")
    return sorted(addon_ids)


def wait_for(condition, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        xbmc.sleep(500)
    return condition()


def depends_first(addon_ids):
    """Order add-ons so dependencies are enabled before what needs them."""
    deps = {}
    for a in addon_ids:
        try:
            root = ET.parse(os.path.join(HOME, "addons", a, "addon.xml")).getroot()
            deps[a] = [i.get("addon") for i in root.iter("import") if i.get("addon") in addon_ids]
        except Exception:
            deps[a] = []
    ordered, seen = [], set()

    def visit(a):
        if a in seen:
            return
        seen.add(a)
        for d in deps.get(a, []):
            visit(d)
        ordered.append(a)

    for a in addon_ids:
        visit(a)
    return ordered


def enable_all(addon_ids):
    xbmc.executebuiltin("UpdateLocalAddons")
    wait_for(lambda: xbmc.getCondVisibility(f"System.HasAddon({SKIN})"), 30)
    xbmc.sleep(2000)
    for a in depends_first(addon_ids):
        if not xbmc.getCondVisibility(f"System.AddonIsEnabled({a})"):
            res = rpc("Addons.SetAddonEnabled", addonid=a, enabled=True)
            if "error" in res:
                log(f"could not enable {a}: {res['error'].get('message')}")


def install_from_kodi_repo():
    for a in EXTRA_FROM_KODI_REPO:
        if xbmc.getCondVisibility(f"System.HasAddon({a})"):
            continue
        log(f"asking Kodi's repository for {a}")
        xbmc.executebuiltin(f"InstallAddon({a})")
        end = time.time() + 180
        while time.time() < end and not xbmc.getCondVisibility(f"System.HasAddon({a})"):
            # Kodi asks to confirm the install (and any dependencies); say yes.
            if xbmc.getCondVisibility("Window.IsActive(yesnodialog)"):
                xbmc.executebuiltin("SendClick(11)")
            xbmc.sleep(1000)


def switch_skin():
    if xbmc.getSkinDir() == SKIN:
        return
    rpc("Settings.SetSettingValue", setting="lookandfeel.skin", value=SKIN)
    # Kodi asks "keep this skin?" for ten seconds, then reverts; say yes.
    if wait_for(lambda: xbmc.getCondVisibility("Window.IsActive(yesnodialog)"), 15):
        xbmc.sleep(500)
        xbmc.executebuiltin("SendClick(11)")


def free_space():
    """Setup is done: delete the bundled copy of everything (tens of MB) and
    any cached copy of the downloaded zip, which matters on boxes with little
    storage."""
    try:
        os.remove(PAYLOAD)
    except OSError as e:
        log(f"could not remove the payload: {e}")
    for folder in (xbmcvfs.translatePath("special://home/addons/packages/"), xbmcvfs.translatePath("special://temp/")):
        try:
            for name in os.listdir(folder):
                if name.startswith("service.benjie.setup") and name.endswith(".zip"):
                    os.remove(os.path.join(folder, name))
        except OSError:
            pass


def run():
    if os.path.isfile(FLAG) or not os.path.isfile(PAYLOAD):
        return
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(8):
        return
    if not xbmcgui.Dialog().yesno(
        "Benjie Setup",
        "Set up Benjie now? This installs the skin and add-ons and switches Kodi to it.",
        yeslabel="Set up",
        nolabel="Not now",
    ):
        log("declined")
        return
    progress = xbmcgui.DialogProgress()
    progress.create("Benjie Setup", "Preparing...")
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        addon_ids = extract(progress)
        log(f"copied {len(addon_ids)} add-ons")
        progress.update(80, "Turning things on...")
        enable_all(addon_ids)
        progress.update(90, "Getting studio logos...")
        install_from_kodi_repo()
        progress.close()
        with open(FLAG, "w") as f:
            f.write(VERSION)
        free_space()
        switch_skin()
        xbmcgui.Dialog().notification("Benjie Setup", "Done. Restart Kodi once to finish.", xbmcgui.NOTIFICATION_INFO, 8000)
        log("finished")
    except Exception as e:
        progress.close()
        log(f"failed: {e}")
        xbmcgui.Dialog().ok("Benjie Setup", f"Setup did not finish: {e}[CR]Install the zip again to retry.")


run()
