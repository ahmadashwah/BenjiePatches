# -*- coding: utf-8 -*-
"""
Runs once at Kodi startup on ANY platform (Android TV, Fire TV, Windows,
macOS, Linux) using Kodi's own built-in Python — no external Python
install, terminal, or keyboard required.

What it does, every time Kodi starts:
  1. Installs/updates the TMDb Bingie Helper player config that wires
     Discover/search into XStream Player.
  2. If XStream Player is installed, vendors the "defusedxml" library into
     its lib folder (pure Python, no compiled parts, safe on any platform).
     This makes epg.py's own code take its normal-and-safer XML parsing
     path instead of its no-defusedxml fallback, which rejects any XMLTV
     feed containing a standard <!DOCTYPE> declaration -- including the
     harmless, universal kind nearly every real provider sends -- leaving
     the EPG permanently empty and PVR search/guide data unusable.
  3. If XStream Player is installed AND is the exact version these patches
     were built against, replaces its addon.py with the pre-patched copy
     bundled in this add-on (with a timestamped backup kept alongside it).
     If the version doesn't match, it logs a warning and skips this step
     rather than risk corrupting a different version's code.
  4. Sets XStream Player as TMDb Bingie Helper's default player, so
     playing/searching doesn't show a "which app" / "which action" chooser
     every time.
  5. Adds a "Live TV" shortcut to the Bingie skin's home menu (native Kodi
     PVR channel list) if the skin's shortcuts config exists and doesn't
     already have one.

Every step is idempotent: it compares against the current file/setting
content first and only writes when something's actually different. All of
this repeats every few minutes for as long as Kodi is running (not just once
at startup), since other add-ons (e.g. script.skinshortcuts) manage some of
the same files and can silently revert a fix shortly after boot.
"""

import os
import shutil
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
KODI_HOME = xbmcvfs.translatePath("special://home/")
KODI_PROFILE = xbmcvfs.translatePath("special://profile/")

EXPECTED_XSTREAM_VERSION = "2.1.5"
LOG_PREFIX = "[IPTV Helper Fixes]"


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"{LOG_PREFIX} {message}", level)


def notify(message):
    xbmc.executebuiltin(f"Notification(IPTV Helper Fixes,{message},5000)")


def get_installed_version(addon_xml_path):
    try:
        tree = ET.parse(addon_xml_path)
        return tree.getroot().attrib.get("version", "")
    except Exception as exc:
        log(f"Could not read version from {addon_xml_path}: {exc}", xbmc.LOGWARNING)
        return None


def install_defusedxml(xstream_dir):
    """Vendors the defusedxml library into XStream Player's lib folder. Pure
    Python, no compiled parts, works on any platform/version — not gated on
    EXPECTED_XSTREAM_VERSION since it only adds a file, never touches
    XStream Player's own code."""
    target_dir = os.path.join(xstream_dir, "resources", "lib", "defusedxml")
    source_dir = os.path.join(ADDON_PATH, "resources", "defusedxml")

    if not os.path.isdir(source_dir):
        log(f"Bundled defusedxml missing at {source_dir} — add-on may be corrupt.", xbmc.LOGERROR)
        return

    changed = False
    for filename in os.listdir(source_dir):
        src_file = os.path.join(source_dir, filename)
        if not os.path.isfile(src_file):
            continue
        dst_file = os.path.join(target_dir, filename)
        with open(src_file, "rb") as f:
            src_bytes = f.read()
        dst_bytes = None
        if os.path.isfile(dst_file):
            with open(dst_file, "rb") as f:
                dst_bytes = f.read()
        if src_bytes != dst_bytes:
            os.makedirs(target_dir, exist_ok=True)
            shutil.copyfile(src_file, dst_file)
            changed = True

    if changed:
        log("Installed/updated defusedxml (fixes EPG parsing for standard XMLTV feeds).")
    else:
        log("defusedxml already up to date.")


def add_live_tv_shortcut():
    """Adds a 'Live TV' home-menu shortcut (native Kodi PVR channel list) to
    the Bingie skin's home menu, if the skin's shortcuts config exists and
    doesn't already have one."""
    shortcuts_path = os.path.join(
        KODI_PROFILE, "addon_data", "script.skinshortcuts", "skin.bingie-mainmenu.DATA.xml"
    )
    if not os.path.isfile(shortcuts_path):
        log("Skin shortcuts file not found — skipping Live TV shortcut (skin not set up yet).")
        return

    try:
        tree = ET.parse(shortcuts_path)
        root = tree.getroot()
    except ET.ParseError as exc:
        log(f"Could not parse skin shortcuts file, leaving it alone: {exc}", xbmc.LOGWARNING)
        return

    shortcuts = root.findall("shortcut")
    for shortcut in shortcuts:
        action_el = shortcut.find("action")
        if action_el is not None and action_el.text and "TVChannels" in action_el.text:
            log("Live TV shortcut already present.")
            return

    new_shortcut = ET.Element("shortcut")
    ET.SubElement(new_shortcut, "defaultID")
    ET.SubElement(new_shortcut, "label").text = "Live TV"
    ET.SubElement(new_shortcut, "label2").text = "Custom item"
    ET.SubElement(new_shortcut, "icon").text = "shortcuts/tv.png"
    ET.SubElement(new_shortcut, "thumb").text = "thumb"
    ET.SubElement(new_shortcut, "action").text = "ActivateWindow(TVChannels,return)"

    insert_index = len(shortcuts)
    for i, shortcut in enumerate(shortcuts):
        default_id_el = shortcut.find("defaultID")
        if default_id_el is not None and (default_id_el.text or "").strip() == "movies":
            insert_index = i + 1
            break

    root.insert(insert_index, new_shortcut)

    try:
        ET.indent(tree, space="\t")
    except AttributeError:
        pass
    tree.write(shortcuts_path, encoding="UTF-8", xml_declaration=False)
    log("Added Live TV shortcut to home menu.")
    notify("Live TV shortcut added to home menu")


def patch_xstream_player():
    """Returns True if XStream Player is present and now matches the patched copy."""
    xstream_dir = os.path.join(KODI_HOME, "addons", "plugin.video.xstream-player")
    addon_xml = os.path.join(xstream_dir, "addon.xml")
    if not os.path.isdir(xstream_dir):
        log("XStream Player not installed yet — skipping (will check again next startup).")
        return False

    install_defusedxml(xstream_dir)

    version = get_installed_version(addon_xml)
    if version != EXPECTED_XSTREAM_VERSION:
        log(
            f"XStream Player is version {version}, but these patches were built "
            f"against {EXPECTED_XSTREAM_VERSION} — skipping rather than risk "
            "corrupting a different version's code.",
            xbmc.LOGWARNING,
        )
        return False

    target = os.path.join(xstream_dir, "resources", "lib", "addon.py")
    source = os.path.join(ADDON_PATH, "resources", "patched_addon.py")
    if not os.path.isfile(target):
        log(f"Expected XStream Player's addon.py at {target} but it's not there.", xbmc.LOGWARNING)
        return False
    if not os.path.isfile(source):
        log(f"Bundled patched addon.py missing at {source} — add-on may be corrupt.", xbmc.LOGERROR)
        return False

    with open(target, "rb") as f:
        current = f.read()
    with open(source, "rb") as f:
        patched = f.read()

    if current == patched:
        log("XStream Player addon.py already up to date.")
        return True

    backup = target + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"
    # copyfile() (not copy2()/copy()) — Android's storage layer often refuses
    # the permission/timestamp metadata copy those do, even though a plain
    # content copy works fine.
    shutil.copyfile(target, backup)
    shutil.copyfile(source, target)
    log(f"Patched XStream Player addon.py (backup saved as {os.path.basename(backup)}).")
    return True


def install_player_config():
    """Returns True if TMDb Bingie Helper is present and the player config is up to date."""
    helper_dir = os.path.join(KODI_HOME, "addons", "plugin.video.tmdb.bingie.helper")
    if not os.path.isdir(helper_dir):
        log("TMDb Bingie Helper not installed yet — skipping (will check again next startup).")
        return False

    players_dir = os.path.join(
        KODI_PROFILE, "addon_data", "plugin.video.tmdb.bingie.helper", "players"
    )
    os.makedirs(players_dir, exist_ok=True)
    target = os.path.join(players_dir, "autogen.plugin.video.xstream-player.json")
    source = os.path.join(ADDON_PATH, "resources", "player_config.json")

    if not os.path.isfile(source):
        log(f"Bundled player config missing at {source} — add-on may be corrupt.", xbmc.LOGERROR)
        return False

    with open(source, "r", encoding="utf-8") as f:
        desired = f.read()

    current = None
    if os.path.isfile(target):
        with open(target, "r", encoding="utf-8") as f:
            current = f.read()

    if current == desired:
        log("Player config already up to date.")
        return True

    with open(target, "w", encoding="utf-8") as f:
        f.write(desired)
    log(f"Installed player config -> {target}")
    return True


def apply_default_player_settings():
    """Merges the default-player settings into TMDb Bingie Helper's settings.xml
    without disturbing any other settings already in that file."""
    helper_dir = os.path.join(KODI_HOME, "addons", "plugin.video.tmdb.bingie.helper")
    if not os.path.isdir(helper_dir):
        return  # Nothing to configure yet — install_player_config() already logged this

    settings_dir = os.path.join(
        KODI_PROFILE, "addon_data", "plugin.video.tmdb.bingie.helper"
    )
    os.makedirs(settings_dir, exist_ok=True)
    settings_path = os.path.join(settings_dir, "settings.xml")

    desired = {
        "default_player_movies": "autogen.plugin.video.xstream-player.json search_movie",
        "default_player_episodes": "autogen.plugin.video.xstream-player.json search_episode",
        "default_player_provider": "true",
        "default_player_kodi": "0",
    }

    if os.path.isfile(settings_path):
        try:
            tree = ET.parse(settings_path)
            root = tree.getroot()
        except ET.ParseError as exc:
            log(f"Could not parse existing settings.xml, leaving it alone: {exc}", xbmc.LOGWARNING)
            return
    else:
        root = ET.Element("settings", version="2")
        tree = ET.ElementTree(root)

    existing = {el.get("id"): el for el in root.findall("setting")}
    changed = False
    for setting_id, value in desired.items():
        el = existing.get(setting_id)
        if el is not None:
            if el.text != value or "default" in el.attrib:
                el.text = value
                el.attrib.pop("default", None)
                changed = True
        else:
            new_el = ET.SubElement(root, "setting", id=setting_id)
            new_el.text = value
            changed = True

    if not changed:
        log("Default player settings already up to date.")
        return

    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass  # Python < 3.9 — harmless to skip, just less pretty-printed
    tree.write(settings_path, encoding="UTF-8", xml_declaration=False)
    log(f"Updated default player settings -> {settings_path}")


RECHECK_INTERVAL_SECONDS = 300


def run_checks():
    """One pass of all checks. Returns True if the core fixes (player config
    + XStream Player patch) are in place."""
    log("Checking XStream Player + Bingie fixes...")
    config_ok = install_player_config()
    patch_ok = patch_xstream_player()
    apply_default_player_settings()
    add_live_tv_shortcut()
    return config_ok and patch_ok


def main():
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(5):
        return  # Kodi is already shutting down

    # Runs every RECHECK_INTERVAL_SECONDS for as long as Kodi is up, not just
    # once at startup — script.skinshortcuts (and possibly other add-ons)
    # manage some of the same files we touch (e.g. the skin shortcuts data)
    # and can resync/overwrite them shortly after our own startup pass runs,
    # silently undoing a fix. Rechecking periodically catches and re-applies
    # anything that gets reverted, instead of only fixing it once per boot.
    notified = False
    while not monitor.abortRequested():
        try:
            core_ok = run_checks()
        except Exception:
            import traceback

            log(traceback.format_exc(), xbmc.LOGERROR)
            core_ok = False

        if core_ok and not notified:
            marker_dir = os.path.join(KODI_PROFILE, "addon_data", ADDON_ID)
            os.makedirs(marker_dir, exist_ok=True)
            marker = os.path.join(marker_dir, "applied_once.flag")
            if not os.path.isfile(marker):
                with open(marker, "w") as f:
                    f.write("done")
                notify("XStream Player fixes applied")
            notified = True

        log(f"Done. Re-checking in {RECHECK_INTERVAL_SECONDS}s.")
        if monitor.waitForAbort(RECHECK_INTERVAL_SECONDS):
            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        tb = traceback.format_exc()
        log(tb, xbmc.LOGERROR)
        try:
            import xbmcgui

            xbmcgui.Dialog().textviewer("IPTV Helper Fixes - Error", tb)
        except Exception as exc:
            log(f"Could not even show the error dialog: {exc}", xbmc.LOGERROR)
