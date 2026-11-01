# -*- coding: utf-8 -*-
"""Optional "Connect GitHub" step for the cross-device watch-progress sync.

Uses GitHub's device login: Kodi shows a short code, the person approves it on
their phone or computer at github.com/login/device, and Kodi receives a token
that belongs to them (gist scope only). The sync then keeps their progress in
a private gist in their own account. Nothing secret ships with the add-on: the
OAuth app's client ID in resources/github_client_id.txt is public by design.
With that file empty the whole feature stays dormant.
"""
import json
import os
import time

import requests
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

LOG_PREFIX = "[IPTV Helper Fixes] [github]"
HTTP_TIMEOUT = 15
SCOPE = "gist"


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"{LOG_PREFIX} {message}", level)


def client_id():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "github_client_id.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def is_available():
    return bool(client_id())


def is_connected():
    svc = xbmcaddon.Addon()
    return svc.getSetting("github_sync_enabled").lower() == "true" and bool(svc.getSetting("github_sync_token").strip())


def _post(url, data):
    r = requests.post(url, data=data, headers={"Accept": "application/json", "User-Agent": "iptvhelperfixes"}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _login_name(token):
    try:
        r = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "iptvhelperfixes"},
            timeout=HTTP_TIMEOUT,
        )
        return r.json().get("login", "") if r.ok else ""
    except Exception:
        return ""


def connect():
    """Runs the device login. Returns True when connected."""
    cid = client_id()
    dialog = xbmcgui.Dialog()
    if not cid:
        dialog.ok("GitHub sync", "GitHub sign-in is not set up in this build yet.")
        return False
    try:
        start = _post("https://github.com/login/device/code", {"client_id": cid, "scope": SCOPE})
        if "device_code" not in start:
            log(f"GitHub refused the device login: {start.get('error')} {start.get('error_description', '')}", xbmc.LOGERROR)
            dialog.ok("GitHub sync", "GitHub sign-in is not set up correctly in this build.")
            return False
        device_code = start["device_code"]
        user_code = start["user_code"]
        uri = start.get("verification_uri", "https://github.com/login/device")
        interval = max(5, int(start.get("interval", 5)))
        expires = time.time() + int(start.get("expires_in", 900))
    except Exception as e:
        log(f"could not start the device login: {e}", xbmc.LOGERROR)
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (401, 404, 422):
            dialog.ok("GitHub sync", "GitHub sign-in is not set up correctly in this build.")
        else:
            dialog.ok("GitHub sync", "Could not reach GitHub. Check the internet connection and try again.")
        return False

    progress = xbmcgui.DialogProgress()
    progress.create(
        "Connect GitHub",
        f"On your phone or computer open [B]{uri.replace('https://', '')}[/B][CR]"
        f"and enter this code:  [B]{user_code}[/B][CR]Waiting for you to approve...",
    )
    token = ""
    monitor = xbmc.Monitor()
    total = max(1, expires - time.time())
    try:
        while time.time() < expires:
            if progress.iscanceled() or monitor.abortRequested():
                return False
            progress.update(
                int(100 * (1 - (expires - time.time()) / total)),
                f"On your phone or computer open [B]{uri.replace('https://', '')}[/B][CR]"
                f"and enter this code:  [B]{user_code}[/B][CR]Waiting for you to approve...",
            )
            if monitor.waitForAbort(interval):
                return False
            try:
                res = _post(
                    "https://github.com/login/oauth/access_token",
                    {
                        "client_id": cid,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
            except Exception as e:
                log(f"poll error: {e}", xbmc.LOGWARNING)
                continue
            err = res.get("error")
            if res.get("access_token"):
                token = res["access_token"]
                break
            if err == "slow_down":
                interval += 5
            elif err in ("expired_token", "access_denied"):
                break
    finally:
        progress.close()

    if not token:
        dialog.ok("GitHub sync", "GitHub was not connected. You can try again from this add-on's settings.")
        return False

    svc = xbmcaddon.Addon()
    svc.setSetting("github_sync_token", token)
    svc.setSetting("github_sync_gist_id", "")
    svc.setSetting("github_sync_enabled", "true")
    name = _login_name(token)
    log(f"connected as {name or 'unknown'}")
    dialog.notification("GitHub sync", f"Connected{(' as ' + name) if name else ''}. Syncing starts now.", xbmcgui.NOTIFICATION_INFO, 6000)
    try:
        import github_sync

        github_sync.run_sync()
    except Exception as e:
        log(f"first sync failed: {e}", xbmc.LOGWARNING)
    return True


def disconnect():
    svc = xbmcaddon.Addon()
    if not is_connected() and not svc.getSetting("github_sync_token").strip():
        xbmcgui.Dialog().ok("GitHub sync", "GitHub is not connected.")
        return
    if xbmcgui.Dialog().yesno("GitHub sync", "Disconnect GitHub? Progress stays in your gist but stops syncing from this device."):
        svc.setSetting("github_sync_enabled", "false")
        svc.setSetting("github_sync_token", "")
        svc.setSetting("github_sync_gist_id", "")
        xbmcgui.Dialog().notification("GitHub sync", "Disconnected", xbmcgui.NOTIFICATION_INFO, 4000)


def offer_once(has_login):
    """One-time, skippable offer shown after an IPTV login exists."""
    if not is_available() or is_connected() or not has_login:
        return
    marker_dir = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo("profile"))
    marker = os.path.join(marker_dir, "github_offer_shown.flag")
    if os.path.isfile(marker):
        return
    if xbmc.getCondVisibility("Window.IsActive(fullscreenvideo)"):
        return
    os.makedirs(marker_dir, exist_ok=True)
    with open(marker, "w") as f:
        f.write("1")
    if xbmcgui.Dialog().yesno(
        "Sync your progress?",
        "Keep your watch progress in step across your devices.[CR]Needs a free GitHub account. You can also do this later from this add-on's settings.",
        yeslabel="Connect",
        nolabel="Not now",
    ):
        connect()
