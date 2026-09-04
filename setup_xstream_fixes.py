#!/usr/bin/env python3
"""
Applies the XStream Player + Bingie fixes to a Kodi install on this machine.

Run this AFTER you've already:
  1. Installed Kodi
  2. Installed the Bingie skin (and its bundled plugin.video.tmdb.bingie.helper)
  3. Installed XStream Player and set up your Xtream Codes profile

This script must sit in the same folder as:
  - addon.py
  - autogen.plugin.video.xstream-player.json

What it does:
  - Verifies XStream Player is installed and is version 2.1.5 (the version
    these fixes were built against). If it's a different version, it stops
    and does NOT touch anything, since the patched addon.py may not match.
  - Verifies TMDb Bingie Helper is installed.
  - Backs up the existing addon.py (adds a .bak-<timestamp> copy) then
    replaces it with the pre-patched version sitting next to this script.
  - Creates the TMDb Bingie Helper "players" folder if needed and copies in
    the player config JSON.

Safe to re-run: it will just re-do the same copy each time.
"""

import os
import platform
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET

EXPECTED_XSTREAM_VERSION = "2.1.5"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_ADDON_PY = os.path.join(SCRIPT_DIR, "addon.py")
SOURCE_PLAYER_JSON = os.path.join(SCRIPT_DIR, "autogen.plugin.video.xstream-player.json")


def find_kodi_root():
    """Return the Kodi userdata root, matching how Kodi resolves special://profile."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return os.path.join(appdata, "Kodi")
    if system == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Kodi")
    # Linux and anything else Kodi-on-Linux-like
    return os.path.expanduser("~/.kodi")


def pause_before_exit():
    """Keep the console window open if this was double-clicked instead of run from a terminal."""
    try:
        input("\nPress Enter to close this window...")
    except EOFError:
        pass


def fail(message):
    print(f"\n[STOPPED] {message}")
    pause_before_exit()
    sys.exit(1)


def main():
    print("XStream Player + Bingie fix installer")
    print("=" * 40)

    if not os.path.isfile(SOURCE_ADDON_PY):
        fail(f"Expected to find addon.py next to this script at:\n  {SOURCE_ADDON_PY}")
    if not os.path.isfile(SOURCE_PLAYER_JSON):
        fail(f"Expected to find the player JSON next to this script at:\n  {SOURCE_PLAYER_JSON}")

    kodi_root = find_kodi_root()
    if not kodi_root or not os.path.isdir(kodi_root):
        fail(
            "Could not find your Kodi folder automatically "
            f"(looked for: {kodi_root}).\n"
            "Make sure Kodi has been run at least once, or edit "
            "find_kodi_root() in this script to point at the right path."
        )
    print(f"Kodi folder: {kodi_root}")

    # --- Verify XStream Player is installed and the right version ---
    xstream_dir = os.path.join(kodi_root, "addons", "plugin.video.xstream-player")
    xstream_addon_xml = os.path.join(xstream_dir, "addon.xml")
    if not os.path.isfile(xstream_addon_xml):
        fail(
            "XStream Player doesn't appear to be installed yet "
            f"(no addon.xml at {xstream_addon_xml}).\n"
            "Install it in Kodi first, then re-run this script."
        )

    tree = ET.parse(xstream_addon_xml)
    installed_version = tree.getroot().attrib.get("version", "")
    print(f"XStream Player version installed: {installed_version}")
    if installed_version != EXPECTED_XSTREAM_VERSION:
        fail(
            f"Installed XStream Player is version {installed_version}, but these "
            f"fixes were built and verified against version {EXPECTED_XSTREAM_VERSION}.\n"
            "The patched addon.py may not match this version's code — stopping "
            "rather than risk corrupting it. Report this version number back so "
            "the patches can be re-derived against it."
        )

    # --- Verify TMDb Bingie Helper is installed ---
    helper_dir = os.path.join(kodi_root, "addons", "plugin.video.tmdb.bingie.helper")
    if not os.path.isdir(helper_dir):
        fail(
            "plugin.video.tmdb.bingie.helper doesn't appear to be installed "
            f"(no folder at {helper_dir}).\n"
            "Install the Bingie skin first (it installs this automatically), "
            "then re-run this script."
        )

    # --- Step 1: back up and replace addon.py ---
    target_addon_py = os.path.join(xstream_dir, "resources", "lib", "addon.py")
    if not os.path.isfile(target_addon_py):
        fail(f"Expected XStream Player's addon.py at:\n  {target_addon_py}\nbut it's not there.")

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_path = target_addon_py + f".bak-{timestamp}"
    shutil.copy2(target_addon_py, backup_path)
    print(f"Backed up original addon.py -> {backup_path}")

    shutil.copy2(SOURCE_ADDON_PY, target_addon_py)
    print(f"Installed patched addon.py -> {target_addon_py}")

    # --- Step 2: install the player config JSON ---
    players_dir = os.path.join(
        kodi_root, "userdata", "addon_data", "plugin.video.tmdb.bingie.helper", "players"
    )
    os.makedirs(players_dir, exist_ok=True)
    target_json = os.path.join(players_dir, "autogen.plugin.video.xstream-player.json")
    shutil.copy2(SOURCE_PLAYER_JSON, target_json)
    print(f"Installed player config -> {target_json}")

    print("\nDone. Reload the skin (or restart Kodi) for the changes to take effect.")
    print(
        "Reminder: you still need to enter your own Xtream Codes credentials "
        "in XStream Player's Profiles settings if you haven't already — "
        "this script only applies the code/config fixes, not your account details."
    )
    pause_before_exit()


if __name__ == "__main__":
    main()
