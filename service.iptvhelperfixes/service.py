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
  5. If Bingie Widgets is installed AND is the exact version this patch was
     built against, patches its "My List" widget to read XStream Player's
     own favorites instead of Kodi's always-empty video library.
  6. Installs/updates the Benjie skin (skin.benjie: Bingie with every skin
     change this add-on used to patch in at runtime built in) and moves a
     device that is still on skin.bingie over to it once (skin_migration).
     The skin itself is no longer patched.

Every step is idempotent: it compares against the current file/setting
content first and only writes when something's actually different. All of
this repeats every few minutes for as long as Kodi is running (not just once
at startup).
"""

import json
import os
import re
import shutil
import threading
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

import error_report
import github_sync
import skin_migration

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
KODI_HOME = xbmcvfs.translatePath("special://home/")
KODI_PROFILE = xbmcvfs.translatePath("special://profile/")

EXPECTED_XSTREAM_VERSION = "2.1.5"
EXPECTED_TMDB_HELPER_VERSION = "1.0.3"
EXPECTED_BINGIE_WIDGETS_VERSION = "1.0.1"
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


_netflix_warm_thread = None


def warm_netflix_top10():
    """Keeps the Netflix Top 10 rows' cache fresh in the background: a cold
    build takes 4-6s (it looks every title up on TMDb), so Home should
    never be what triggers it. Cheap (about 0.1s) while the cache is fresh."""
    global _netflix_warm_thread
    if _netflix_warm_thread is not None and _netflix_warm_thread.is_alive():
        return
    if not xbmc.getCondVisibility("System.HasAddon(plugin.video.xstream-player)"):
        return

    def _run():
        for kind in ("tv", "movie"):
            try:
                xbmc.executeJSONRPC(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "Files.GetDirectory",
                            "params": {
                                "directory": f"plugin://plugin.video.xstream-player/?mode=netflix_top10&type={kind}",
                                "media": "video",
                            },
                        }
                    )
                )
            except Exception as e:
                log(f"Netflix Top 10 warm-up ({kind}) failed: {e}", xbmc.LOGWARNING)

    import threading

    _netflix_warm_thread = threading.Thread(target=_run, daemon=True)
    _netflix_warm_thread.start()


def update_profile_label():
    """Publishes the active XStream Player profile's name for the side menu
    header (falls back to "IPTV Account" until one has been entered)."""
    name = ""
    try:
        addon = xbmcaddon.Addon("plugin.video.xstream-player")
        m = re.search(r"(\d+)", addon.getSetting("active_pvr_profile") or "")
        num = m.group(1) if m else "1"
        name = (addon.getSetting(f"profile_{num}_name") or "").strip()
        if re.fullmatch(r"Profile \d+", name):
            name = ""
    except Exception as e:
        log(f"profile name not read: {e}")
    xbmc.executebuiltin("SetProperty(XStreamProfileName,%s,Home)" % (name or "IPTV Account").replace(",", " "))


def first_run_welcome():
    """Once, on a fresh install with no IPTV login entered yet: offers to
    open the login settings straight away (it is also under the profile name
    at the top of the side menu). What the error reports are is explained in
    the build's INSTALL.txt and the add-on's settings."""
    marker_dir = os.path.join(KODI_PROFILE, "addon_data", ADDON_ID)
    marker = os.path.join(marker_dir, "welcome_shown.flag")
    if os.path.isfile(marker):
        return
    try:
        xs = xbmcaddon.Addon("plugin.video.xstream-player")
    except Exception:
        return
    has_login = any(
        (xs.getSetting(f"profile_{n}_xtream_url") or xs.getSetting(f"profile_{n}_m3u") or "").strip()
        for n in range(1, 11)
    )
    os.makedirs(marker_dir, exist_ok=True)
    with open(marker, "w") as f:
        f.write("done")
    if has_login:
        return
    import xbmcgui

    if xbmcgui.Dialog().yesno(
        "Welcome",
        "Enter your IPTV login to get started.[CR]"
        "You can also do it any time from the name at the top of the side menu.",
        yeslabel="Enter login",
        nolabel="Later",
    ):
        xbmc.executebuiltin("RunPlugin(plugin://plugin.video.xstream-player/?mode=settings)")


_live_tv_thread = None


def _has_iptv_login():
    try:
        xs = xbmcaddon.Addon("plugin.video.xstream-player")
    except Exception:
        return False
    for n in range(1, 11):
        if xs.getSetting(f"profile_{n}_enabled") == "false":
            continue
        if xs.getSetting(f"profile_{n}_m3u").strip() or (
            xs.getSetting(f"profile_{n}_xtream_url").strip()
            and xs.getSetting(f"profile_{n}_xtream_username").strip()
            and xs.getSetting(f"profile_{n}_xtream_password").strip()
        ):
            return True
    return False


def _live_tv_state_path():
    return os.path.join(KODI_PROFILE, "addon_data", ADDON_ID, "live_tv_setup.json")


def _offer_github_sync():
    """Once an IPTV login exists, offers the optional GitHub sign-in (see
    github_login). Dormant until the build carries a GitHub client ID."""
    try:
        import github_login

        if github_login.is_available() and not xbmc.Monitor().waitForAbort(60):
            github_login.offer_once(_has_iptv_login())
    except Exception as e:
        log(f"GitHub offer skipped: {e}", xbmc.LOGWARNING)


def ensure_live_tv():
    """A new install shows an empty Live TV list: the Live TV add-on
    (pvr.iptvsimple) is not installed, or not switched on, and XStream
    Player's channel sync has never run. Once an IPTV login exists, installs
    and enables that add-on if needed and runs the channel sync, with limits
    so it never loops: at most 3 install attempts, and a sync only when there
    are no channels and none was started in the last 12 hours. Runs in the
    background, a minute and a half after start so the Live TV add-on has had
    its chance to load by itself."""
    global _live_tv_thread
    if _live_tv_thread is not None and _live_tv_thread.is_alive():
        return

    def _work():
        monitor = xbmc.Monitor()
        if monitor.waitForAbort(90) or not _has_iptv_login():
            return
        path = _live_tv_state_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            state = {}

        def save():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f)

        if not xbmc.getCondVisibility("System.HasAddon(pvr.iptvsimple)"):
            if state.get("install_attempts", 0) >= 3:
                return
            state["install_attempts"] = state.get("install_attempts", 0) + 1
            save()
            log("Live TV add-on missing: asking Kodi to install pvr.iptvsimple.")
            xbmc.executebuiltin("InstallAddon(pvr.iptvsimple)")
            end = time.time() + 180
            while time.time() < end and not xbmc.getCondVisibility("System.HasAddon(pvr.iptvsimple)"):
                if xbmc.getCondVisibility("Window.IsActive(yesnodialog)"):
                    xbmc.executebuiltin("SendClick(11)")
                if monitor.waitForAbort(1):
                    return
        if not xbmc.getCondVisibility("System.HasAddon(pvr.iptvsimple)"):
            log("pvr.iptvsimple could not be installed.", xbmc.LOGWARNING)
            return
        if not xbmc.getCondVisibility("System.AddonIsEnabled(pvr.iptvsimple)"):
            xbmc.executeJSONRPC(json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "Addons.SetAddonEnabled",
                "params": {"addonid": "pvr.iptvsimple", "enabled": True},
            }))
            monitor.waitForAbort(5)
        if xbmc.getCondVisibility("PVR.HasTVChannels"):
            return
        if time.time() - state.get("last_sync", 0) < 12 * 3600:
            return
        state["last_sync"] = time.time()
        save()
        log("No Live TV channels yet: running XStream Player's channel sync (pvr_sync_silent).")
        xbmc.executebuiltin("RunPlugin(plugin://plugin.video.xstream-player/?mode=pvr_sync_silent)")

    _live_tv_thread = threading.Thread(target=_work, daemon=True)
    _live_tv_thread.start()


class _PlaybackWatcher(xbmc.Player):
    """Closes the loading window once playback has actually started (or failed
    to). Deliberately not the stopped/ended events: those also fire for the
    previous item when a new play request replaces it, which would close the
    window while the new stream is still being found."""

    @staticmethod
    def _close():
        xbmc.executebuiltin("ClearProperty(PlaybackLoading,Home)")

    def onAVStarted(self):
        self._close()

    def onPlayBackError(self):
        self._close()


_playback_watcher = None


_XSTREAM_PATCHED_FILES = [
    ("addon.py", "patched_addon.py"),
    ("history.py", "patched_history.py"),
]


def patch_xstream_player():
    """Returns True if XStream Player is present and all patched files now
    match the bundled copies."""
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

    all_ok = True
    for target_name, source_name in _XSTREAM_PATCHED_FILES:
        target = os.path.join(xstream_dir, "resources", "lib", target_name)
        source = os.path.join(ADDON_PATH, "resources", source_name)
        if not os.path.isfile(target):
            log(f"Expected XStream Player's {target_name} at {target} but it's not there.", xbmc.LOGWARNING)
            all_ok = False
            continue
        if not os.path.isfile(source):
            log(f"Bundled patched {target_name} missing at {source} — add-on may be corrupt.", xbmc.LOGERROR)
            all_ok = False
            continue

        with open(target, "rb") as f:
            current = f.read()
        with open(source, "rb") as f:
            patched = f.read()

        if current == patched:
            log(f"XStream Player {target_name} already up to date.")
            continue

        backup = target + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"
        # copyfile() (not copy2()/copy()) — Android's storage layer often
        # refuses the permission/timestamp metadata copy those do, even
        # though a plain content copy works fine.
        shutil.copyfile(target, backup)
        shutil.copyfile(source, target)
        log(f"Patched XStream Player {target_name} (backup saved as {os.path.basename(backup)}).")

    return all_ok


def patch_tmdb_bingie_helper():
    """Replaces TMDb Bingie Helper's own items/trakt.py with a patched copy
    that checks XStream Player's real watch history (via a new
    discover_watch_export mode, cross-addon Files.GetDirectory call, cached
    per show) before falling through to its original Trakt-based lookups
    for get_playcount/set_playprogress on episode items -- so Discover's
    episode tiles show real watched/progress status instead of always
    appearing unwatched, since nothing in this setup scrobbles to Trakt.
    Version-gated like patch_xstream_player(): skips rather than risk
    corrupting a different version's code."""
    helper_dir = os.path.join(KODI_HOME, "addons", "plugin.video.tmdb.bingie.helper")
    addon_xml = os.path.join(helper_dir, "addon.xml")
    if not os.path.isdir(helper_dir):
        log("TMDb Bingie Helper not installed yet — skipping (will check again next startup).")
        return False

    version = get_installed_version(addon_xml)
    if version != EXPECTED_TMDB_HELPER_VERSION:
        log(
            f"TMDb Bingie Helper is version {version}, but this patch was built "
            f"against {EXPECTED_TMDB_HELPER_VERSION} — skipping rather than risk "
            "corrupting a different version's code.",
            xbmc.LOGWARNING,
        )
        return False

    target = os.path.join(helper_dir, "resources", "tmdbbingiehelper", "lib", "items", "trakt.py")
    source = os.path.join(ADDON_PATH, "resources", "patched_tmdb_trakt.py")
    if not os.path.isfile(target):
        log(f"Expected TMDb Bingie Helper's trakt.py at {target} but it's not there.", xbmc.LOGWARNING)
        return False
    if not os.path.isfile(source):
        log(f"Bundled patched trakt.py missing at {source} — add-on may be corrupt.", xbmc.LOGERROR)
        return False

    with open(target, "rb") as f:
        current = f.read()
    with open(source, "rb") as f:
        patched = f.read()

    if current == patched:
        log("TMDb Bingie Helper trakt.py already up to date.")
        return True

    backup = target + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copyfile(target, backup)
    shutil.copyfile(source, target)
    log(f"Patched TMDb Bingie Helper trakt.py (backup saved as {os.path.basename(backup)}).")
    return True


_BINGIE_WIDGETS_PATCHED_FILES = [
    ("media.py", "patched_widgets_media.py"),
    ("tvshows.py", "patched_widgets_tvshows.py"),
]


def patch_bingie_widgets_mylist():
    """Replaces script.bingie.widgets' media.py/tvshows.py mylist() methods
    with patched copies that read XStream Player's own favorites (via a new
    favorites_widget_export mode, cross-addon Files.GetDirectory call)
    instead of only querying Kodi's own video library -- which is always
    empty on this setup (pure plugin-source content, nothing scanned into
    it), so the Home screen's "My List" widget never showed anything no
    matter what got favorited. Falls back to the untouched original library
    query if XStream Player isn't installed or returns nothing, so this is
    never worse than before. Version-gated like patch_xstream_player():
    skips rather than risk corrupting a different version's code."""
    widgets_dir = os.path.join(KODI_HOME, "addons", "script.bingie.widgets")
    addon_xml = os.path.join(widgets_dir, "addon.xml")
    if not os.path.isdir(widgets_dir):
        log("Bingie Widgets not installed yet — skipping (will check again next startup).")
        return False

    version = get_installed_version(addon_xml)
    if version != EXPECTED_BINGIE_WIDGETS_VERSION:
        log(
            f"Bingie Widgets is version {version}, but this patch was built "
            f"against {EXPECTED_BINGIE_WIDGETS_VERSION} — skipping rather than "
            "risk corrupting a different version's code.",
            xbmc.LOGWARNING,
        )
        return False

    all_ok = True
    for target_name, source_name in _BINGIE_WIDGETS_PATCHED_FILES:
        target = os.path.join(widgets_dir, "resources", "lib", target_name)
        source = os.path.join(ADDON_PATH, "resources", source_name)
        if not os.path.isfile(target):
            log(f"Expected Bingie Widgets' {target_name} at {target} but it's not there.", xbmc.LOGWARNING)
            all_ok = False
            continue
        if not os.path.isfile(source):
            log(f"Bundled patched {target_name} missing at {source} — add-on may be corrupt.", xbmc.LOGERROR)
            all_ok = False
            continue

        with open(target, "rb") as f:
            current = f.read()
        with open(source, "rb") as f:
            patched = f.read()

        if current == patched:
            log(f"Bingie Widgets {target_name} already up to date.")
            continue

        backup = target + f".bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copyfile(target, backup)
        shutil.copyfile(source, target)
        log(f"Patched Bingie Widgets {target_name} (backup saved as {os.path.basename(backup)}).")

    return all_ok


def install_backbutton_keymap():
    """Installs a keymap that repoints the Back/Escape key during
    fullscreen video playback: for a series episode played through
    XStream Player, it now jumps to that show's season in Discover
    instead of just returning to whatever screen was open before
    playback started. Everything else (movies, live TV) is unaffected --
    XStream Player's own handler falls back to a plain stop, the same as
    Kodi's own default Back-during-playback behavior, whenever it isn't
    tracking a series episode as currently playing."""
    keymaps_dir = os.path.join(KODI_PROFILE, "keymaps")
    os.makedirs(keymaps_dir, exist_ok=True)
    target = os.path.join(keymaps_dir, "xstream_backbutton.xml")
    source = os.path.join(ADDON_PATH, "resources", "xstream_backbutton.xml")

    if not os.path.isfile(source):
        log(f"Bundled back-button keymap missing at {source} — add-on may be corrupt.", xbmc.LOGERROR)
        return

    with open(source, "r", encoding="utf-8") as f:
        desired = f.read()

    current = None
    if os.path.isfile(target):
        with open(target, "r", encoding="utf-8") as f:
            current = f.read()

    if current == desired:
        log("Back-button keymap already up to date.")
        return

    with open(target, "w", encoding="utf-8") as f:
        f.write(desired)
    xbmc.executebuiltin("Action(reloadkeymaps)")
    log("Installed/updated back-button keymap and asked Kodi to reload keymaps.")


SUBTITLE_ADDON = "service.subtitles.opensubtitles-com"
LEGACY_SUBTITLE_ADDON = "service.subtitles.opensubtitles"  # the old OpenSubtitles.org one, wrongly installed by 1.7.11
_last_subtitle_install_request = 0.0


def _set_kodi_setting(name, value):
    reply = json.loads(
        xbmc.executeJSONRPC(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "Settings.SetSettingValue",
                    "params": {"setting": name, "value": value},
                }
            )
        )
    )
    return reply.get("result") is True


def setup_subtitles():
    """One-time: installs and enables the official OpenSubtitles.com add-on (service.subtitles.opensubtitles-com -- NOT service.subtitles.opensubtitles, which is the legacy OpenSubtitles.org one),
    sets the preferred subtitle languages to Arabic and English, and makes
    it the default subtitle service for TV shows and movies. It still needs
    a free opensubtitles.com account entered in the add-on's own settings --
    that can't be done from here. Guarded by a flag file so changing any of
    these later in Kodi's settings sticks; retried every ~10 minutes until
    the add-on is actually installed (the install is asynchronous and needs
    the repository to be reachable)."""
    global _last_subtitle_install_request
    marker_dir = os.path.join(KODI_PROFILE, "addon_data", ADDON_ID)
    os.makedirs(marker_dir, exist_ok=True)
    marker = os.path.join(marker_dir, "subtitles_setup_v2.flag")
    if os.path.isfile(marker):
        return

    if not xbmc.getCondVisibility(f"System.HasAddon({SUBTITLE_ADDON})"):
        if time.time() - _last_subtitle_install_request >= 600:
            _last_subtitle_install_request = time.time()
            xbmc.executebuiltin(f"InstallAddon({SUBTITLE_ADDON})")
            log("Requested install of the OpenSubtitles.com subtitle add-on.")
        return

    if not xbmc.getCondVisibility(f"System.AddonIsEnabled({SUBTITLE_ADDON})"):
        xbmc.executeJSONRPC(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "Addons.SetAddonEnabled",
                    "params": {"addonid": SUBTITLE_ADDON, "enabled": True},
                }
            )
        )

    ok = [
        _set_kodi_setting("subtitles.languages", ["Arabic", "English"]),
        _set_kodi_setting("subtitles.tv", SUBTITLE_ADDON),
        _set_kodi_setting("subtitles.movie", SUBTITLE_ADDON),
    ]
    if all(ok):
        if xbmc.getCondVisibility(f"System.AddonIsEnabled({LEGACY_SUBTITLE_ADDON})"):
            xbmc.executeJSONRPC(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "Addons.SetAddonEnabled",
                        "params": {"addonid": LEGACY_SUBTITLE_ADDON, "enabled": False},
                    }
                )
            )
        with open(marker, "w") as f:
            f.write("done")
        log("Subtitles set up: OpenSubtitles.com, Arabic + English (log in via the add-on's settings).")
    else:
        log(f"Subtitle settings not all applied yet ({ok}); will retry.", xbmc.LOGWARNING)


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
    log("Checking XStream Player fixes...")
    config_ok = install_player_config()
    patch_ok = patch_xstream_player()
    apply_default_player_settings()
    install_backbutton_keymap()
    setup_subtitles()
    patch_tmdb_bingie_helper()
    patch_bingie_widgets_mylist()
    try:
        # The skin changes live in skin.benjie now; this installs/updates it
        # and moves a device off skin.bingie once.
        skin_migration.run(xbmc.Monitor())
    except Exception:
        import traceback

        log(traceback.format_exc(), xbmc.LOGERROR)
    update_profile_label()
    threading.Thread(target=first_run_welcome, daemon=True).start()
    ensure_live_tv()
    threading.Thread(target=_offer_github_sync, daemon=True).start()
    warm_netflix_top10()
    try:
        github_sync.run_sync()
    except Exception:
        import traceback

        log(traceback.format_exc(), xbmc.LOGERROR)
    try:
        error_report.run_cycle()
    except Exception as e:
        log(f"[diag] cycle failed: {e}", xbmc.LOGWARNING)
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
    global _playback_watcher
    _playback_watcher = _PlaybackWatcher()
    try:
        error_report.begin_session()
    except Exception as e:
        log(f"[diag] could not start crash tracking: {e}", xbmc.LOGWARNING)
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
        # Wake every 30s to refresh the crash-tracking heartbeat (its last
        # value is the fallback crash time) instead of one long sleep.
        aborted = False
        waited = 0
        while waited < RECHECK_INTERVAL_SECONDS:
            if monitor.waitForAbort(30):
                aborted = True
                break
            waited += 30
            error_report.heartbeat()
            update_profile_label()
        if aborted:
            break

    error_report.end_session()


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
