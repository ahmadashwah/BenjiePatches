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


def _looks_like_kodi_root(path):
    """Sanity-check that a candidate folder actually looks like a Kodi profile folder."""
    return os.path.isdir(os.path.join(path, "addons")) or os.path.isdir(os.path.join(path, "userdata"))


def find_kodi_root():
    """Try every known way Kodi ends up installed on this OS. Returns None if none match."""
    system = platform.system()
    candidates = []
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(os.path.join(appdata, "Kodi"))
        # Microsoft Store (UWP) builds are sandboxed and live under a
        # per-install package folder with a semi-random suffix instead of
        # the normal %APPDATA%\Kodi — search for it rather than guessing
        # the suffix.
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            packages_dir = os.path.join(localappdata, "Packages")
            if os.path.isdir(packages_dir):
                for entry in os.listdir(packages_dir):
                    if entry.startswith("XBMCFoundation.Kodi"):
                        candidates.append(
                            os.path.join(packages_dir, entry, "LocalCache", "Roaming", "Kodi")
                        )
        # Portable installs (zip download run with --portable, or a
        # portable_data folder placed next to the exe) keep everything
        # inside the install folder itself instead of AppData.
        for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env_var)
            if base:
                candidates.append(os.path.join(base, "Kodi", "portable_data"))
        local_appdata_programs = os.environ.get("LOCALAPPDATA")
        if local_appdata_programs:
            candidates.append(
                os.path.join(local_appdata_programs, "Programs", "Kodi", "portable_data")
            )
    elif system == "Darwin":
        candidates.append(os.path.expanduser("~/Library/Application Support/Kodi"))
    else:
        # Linux and anything else Kodi-on-Linux-like
        candidates.append(os.path.expanduser("~/.kodi"))
        candidates.append(os.path.expanduser("~/.var/app/tv.kodi.Kodi/data"))  # Flatpak
        candidates.append(os.path.expanduser("~/snap/kodi/current/.kodi"))  # Snap

    for candidate in candidates:
        if os.path.isdir(candidate) and _looks_like_kodi_root(candidate):
            return candidate
    return None


def ask_for_kodi_root():
    """Last resort when none of the known install patterns matched: ask the user directly."""
    print(
        "\nCouldn't find your Kodi folder automatically — this can happen with "
        "portable installs, unusual install locations, or if Kodi hasn't been "
        "run yet."
    )
    print(
        "In Kodi, check Settings -> System Information (or the 'Profile' path "
        "shown in the System info screen) to see the exact folder, then paste "
        "it below. It should be the folder that directly contains 'addons' and "
        "'userdata' subfolders."
    )
    while True:
        entered = input(
            "\nPath to your Kodi folder (or leave blank to give up): "
        ).strip().strip('"')
        if not entered:
            return None
        if os.path.isdir(entered) and _looks_like_kodi_root(entered):
            return entered
        print(f"That doesn't look like a Kodi folder (no addons/userdata found in: {entered}). Try again.")


def apply_default_player_settings(kodi_root):
    """
    Set TMDb Bingie Helper to always use our player without asking "which app"
    or "which action" every time — matches the values from a working reference
    setup. Merges into the existing settings.xml (creating it if it doesn't
    exist yet) rather than overwriting other settings.
    """
    desired = {
        "default_player_movies": "autogen.plugin.video.xstream-player.json search_movie",
        "default_player_episodes": "autogen.plugin.video.xstream-player.json search_episode",
        "default_player_provider": "true",
        "default_player_kodi": "0",
    }
    userdata_settings_dir = os.path.join(
        kodi_root, "userdata", "addon_data", "plugin.video.tmdb.bingie.helper"
    )
    os.makedirs(userdata_settings_dir, exist_ok=True)
    settings_path = os.path.join(userdata_settings_dir, "settings.xml")

    if os.path.isfile(settings_path):
        tree = ET.parse(settings_path)
        root = tree.getroot()
    else:
        root = ET.Element("settings", version="2")
        tree = ET.ElementTree(root)

    existing = {el.get("id"): el for el in root.findall("setting")}
    for setting_id, value in desired.items():
        if setting_id in existing:
            existing[setting_id].text = value
            existing[setting_id].attrib.pop("default", None)
        else:
            el = ET.SubElement(root, "setting", id=setting_id)
            el.text = value

    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass  # ET.indent needs Python 3.9+; harmless to skip, just less pretty-printed
    tree.write(settings_path, encoding="UTF-8", xml_declaration=False)
    print(f"Set default player (no more 'which app'/'which action' prompts) -> {settings_path}")


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
    if not kodi_root:
        kodi_root = ask_for_kodi_root()
    if not kodi_root or not os.path.isdir(kodi_root):
        fail(
            "Could not find your Kodi folder. Make sure Kodi has been run at "
            "least once and has finished its first-run setup, then try again."
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

    # --- Step 3: make it the default player so no "which app" / "which action"
    #     prompt shows up on every single play (matches the working reference setup) ---
    apply_default_player_settings(kodi_root)

    print("\nDone. Reload the skin (or restart Kodi) for the changes to take effect.")
    print(
        "Reminder: you still need to enter your own Xtream Codes credentials "
        "in XStream Player's Profiles settings if you haven't already — "
        "this script only applies the code/config fixes, not your account details."
    )
    pause_before_exit()


if __name__ == "__main__":
    main()
