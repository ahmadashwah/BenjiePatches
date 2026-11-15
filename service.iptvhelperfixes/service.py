# -*- coding: utf-8 -*-
"""
Runs once at Kodi startup on ANY platform (Android TV, Fire TV, Windows,
macOS, Linux) using Kodi's own built-in Python — no external Python
install, terminal, or keyboard required.

Since 1.9.0 nothing is patched: the skin (skin.benjie), XStream Player, TMDb
Bingie Helper and Bingie Widgets come from the Bengie repository with every
fix built in. What this service still does, every few minutes while Kodi runs:
  - Keeps the Bengie add-ons current and moves a device off skin.bingie once
    (benjie_update: installs the Bengie repository on older devices, then
    any newer Bengie add-on it lists).
  - Back-button keymap, subtitle set-up, Live TV set-up after a login.
  - Publishes the IPTV profile name for the side menu header, closes the
    playback loading screen once a video starts, keeps the Netflix Top 10
    cache warm.
  - Cross-device watch sync and error reports.
"""

import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

import error_report
import github_sync
import benjie_update

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
KODI_HOME = xbmcvfs.translatePath("special://home/")
KODI_PROFILE = xbmcvfs.translatePath("special://profile/")

LOG_PREFIX = "[IPTV Helper Fixes]"


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"{LOG_PREFIX} {message}", level)


def notify(message):
    xbmc.executebuiltin(f"Notification(IPTV Helper Fixes,{message},5000)")


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


def ensure_live_tv(delay=90):
    """A new install shows an empty Live TV list: the Live TV add-on
    (pvr.iptvsimple) is not installed, or not switched on, and XStream
    Player's channel sync has never run. Once an IPTV login exists, installs
    and enables that add-on if needed and runs the channel sync, with limits
    so it never loops: at most 3 install attempts, and a sync only when there
    are no channels and none was started in the last 12 hours. Runs in the
    background; at Kodi start a minute and a half in, so the Live TV add-on
    has had its chance to load by itself, and right away (delay=0) when a
    login has just been entered (see live_tv_after_login)."""
    global _live_tv_thread
    if _live_tv_thread is not None and _live_tv_thread.is_alive():
        return

    def _work():
        monitor = xbmc.Monitor()
        if (delay and monitor.waitForAbort(delay)) or not _has_iptv_login():
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


def disable_empty_live_tv_instance():
    """The Live TV add-on keeps a leftover "Migrated Add-on Config" instance
    (instance 1) with no playlist or guide once XStream Player has set up its
    own instances; it starts as an extra Live TV client at every launch and
    logs load errors for nothing. Switched off once, only when it is exactly
    that empty leftover and XStream's own instance exists (takes effect at the
    next Kodi start)."""
    d = os.path.join(KODI_PROFILE, "addon_data", "pvr.iptvsimple")
    first = os.path.join(d, "instance-settings-1.xml")
    if not os.path.isfile(first):
        return
    try:
        others = [f for f in os.listdir(d) if f.startswith("instance-settings-") and f != "instance-settings-1.xml"]
        if not any("XStream Player" in open(os.path.join(d, f), encoding="utf-8", errors="replace").read() for f in others):
            return
        root = ET.parse(first).getroot()
    except (OSError, ET.ParseError):
        return
    s = {el.get("id"): (el.text or "").strip() for el in root.iter("setting")}
    if s.get("kodi_addon_instance_name") != "Migrated Add-on Config" or s.get("kodi_addon_instance_enabled") == "false":
        return
    if s.get("m3uPath") or s.get("m3uUrl") or s.get("epgPath") or s.get("epgUrl"):
        return  # it has a source of its own: leave it
    for el in root.iter("setting"):
        if el.get("id") == "kodi_addon_instance_enabled":
            el.text = "false"
            el.attrib.pop("default", None)
            break
    else:
        el = ET.SubElement(root, "setting", id="kodi_addon_instance_enabled")
        el.text = "false"
    ET.ElementTree(root).write(first, encoding="utf-8", xml_declaration=False)
    log("Switched off the empty leftover Live TV instance (\"Migrated Add-on Config\"); takes effect at the next start.")


def refresh_empty_guide():
    """XStream Player 2.1.5.1 and earlier wrote the Live TV guide empty (its
    XMLTV export used defusedxml, which cannot build XML). With the fixed
    player, a channel sync writes the real guide; this runs that sync when the
    guide file has no programmes, at most every 12 hours."""
    xs_data = os.path.join(KODI_PROFILE, "addon_data", "plugin.video.xstream-player")
    try:
        guides = [f for f in os.listdir(xs_data) if f.startswith("pvr_epg_") and f.endswith(".xml")]
    except OSError:
        return
    if not guides or not xbmc.getCondVisibility("System.HasPVRAddon") or not _has_iptv_login():
        return
    empty = []
    for g in guides:
        try:
            with open(os.path.join(xs_data, g), "r", encoding="utf-8", errors="replace") as f:
                if "<programme" not in f.read(65536):
                    empty.append(g)
        except OSError:
            pass
    if not empty:
        return
    path = _live_tv_state_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    if time.time() - state.get("last_guide_sync", 0) < 12 * 3600:
        return
    state["last_guide_sync"] = time.time()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    log(f"Live TV guide is empty ({', '.join(empty)}): running XStream Player's channel sync to rebuild it.")
    xbmc.executebuiltin("RunPlugin(plugin://plugin.video.xstream-player/?mode=pvr_sync_silent)")


def live_tv_after_login():
    """Called every 30 s: as soon as an IPTV login exists while Live TV is not
    switched on yet, sets it up straight away instead of on the next 5-minute
    pass (the side menu's Live TV entry appears once it is on)."""
    if xbmc.getCondVisibility("System.HasPVRAddon"):
        return
    if _has_iptv_login():
        ensure_live_tv(delay=0)


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


def disable_versioncheck_once():
    """Once per device: switches off Kodi's own update checker
    (service.xbmc.versioncheck). It took about 6 s of CPU at every start
    (measured on one core), competing with Home's rows on slow boxes, and only
    reports new Kodi releases. A flag file keeps it from repeating, so turning
    it back on in Kodi's add-on settings sticks."""
    marker = os.path.join(KODI_PROFILE, "addon_data", ADDON_ID, "versioncheck_off.flag")
    if os.path.isfile(marker):
        return
    if xbmc.getCondVisibility("System.AddonIsEnabled(service.xbmc.versioncheck)"):
        reply = json.loads(xbmc.executeJSONRPC(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "Addons.SetAddonEnabled",
            "params": {"addonid": "service.xbmc.versioncheck", "enabled": False},
        })))
        if reply.get("result") != "OK":
            log(f"Could not switch off Kodi's version check: {reply.get('error')}", xbmc.LOGWARNING)
            return
        log("Switched off Kodi's version check (one-time; saves its start-up work).")
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    with open(marker, "w") as f:
        f.write("done")


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


RECHECK_INTERVAL_SECONDS = 300


def run_checks():
    """One pass of all checks."""
    log("Checking Bengie...")
    install_backbutton_keymap()
    disable_versioncheck_once()
    try:
        benjie_update.run(xbmc.Monitor())
    except Exception:
        import traceback

        log(traceback.format_exc(), xbmc.LOGERROR)
    update_profile_label()
    # On a new install the skin question comes first; the welcome (enter your
    # login) follows on the next pass once that is settled.
    if not benjie_update.switch_pending():
        # Its install prompt would otherwise sit in front of the skin question.
        setup_subtitles()
        threading.Thread(target=first_run_welcome, daemon=True).start()
    ensure_live_tv()
    try:
        refresh_empty_guide()
        disable_empty_live_tv_instance()
    except Exception as e:
        log(f"Guide check failed: {e}", xbmc.LOGWARNING)
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


def main():
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(5):
        return  # Kodi is already shutting down

    # Runs every RECHECK_INTERVAL_SECONDS for as long as Kodi is up.
    global _playback_watcher
    _playback_watcher = _PlaybackWatcher()
    try:
        error_report.begin_session()
    except Exception as e:
        log(f"[diag] could not start crash tracking: {e}", xbmc.LOGWARNING)
    while not monitor.abortRequested():
        try:
            run_checks()
        except Exception:
            import traceback

            log(traceback.format_exc(), xbmc.LOGERROR)

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
            try:
                live_tv_after_login()
            except Exception as e:
                log(f"Live TV check failed: {e}", xbmc.LOGWARNING)
            if benjie_update.switch_pending():
                # Waiting for Home to switch skins: try again every 30s, then
                # show the welcome as soon as it is done.
                try:
                    benjie_update.migrate_once(monitor)
                    if not benjie_update.switch_pending():
                        threading.Thread(target=first_run_welcome, daemon=True).start()
                except Exception:
                    import traceback

                    log(traceback.format_exc(), xbmc.LOGERROR)
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
