# -*- coding: utf-8 -*-
"""Collects errors and crash times from this device and mirrors them into
the same private GitHub Gist the watch-progress sync already uses, as one
file per device (diag_<device>.json), so every device's problems can be read
from one place.

Two things are recorded:

* Errors/warnings: kodi.log is scanned incrementally for error-level lines
  and for warnings/errors that mention this project's add-ons or the skin
  (our own add-ons log most failures at info level, so the level alone would
  miss them). Consecutive lines from one failure (a Python traceback) are
  merged into one event, identical events are counted instead of repeated,
  and credentials are redacted before anything is stored.
* Crashes: Kodi dying takes the add-on with it, so it can't report itself.
  Instead a session marker is written at startup and flipped to "clean" on a
  normal shutdown; if the next startup finds a marker that was never closed,
  the previous run ended abnormally (crash, force-quit, power loss -- these
  can't be told apart from inside Kodi) and the end of kodi.old.log (the
  previous run's log) is attached with the time of its last line.
"""

import hashlib
import json
import os
import re
import time

import xbmc
import xbmcaddon
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
STATE_DIR = os.path.join(xbmcvfs.translatePath("special://profile/"), "addon_data", ADDON_ID)
SESSION_FILE = os.path.join(STATE_DIR, "diag_session.json")
STATE_FILE = os.path.join(STATE_DIR, "diag_state.json")
DEVICE_FILE = os.path.join(STATE_DIR, "diag_device_id.txt")
LOG_PATH = xbmcvfs.translatePath("special://logpath/kodi.log")
OLD_LOG_PATH = xbmcvfs.translatePath("special://logpath/kodi.old.log")

LOG_PREFIX = "[IPTV Helper Fixes] [diag]"
MAX_SCAN_BYTES = 2_000_000
MAX_ERRORS = 300
MAX_CRASHES = 50
MAX_SAMPLE = 1500
UPLOAD_LIMIT = 350_000

OURS = (
    "[XStream Player]",
    "[IPTV Helper Fixes]",
    "xstream-player",
    "service.iptvhelperfixes",
    "skin.bingie",
    "script.bingie",
    "tmdb.bingie",
    "tmdbbingiehelper",
)
KEYWORDS = re.compile(
    r"error|exception|failed|failure|traceback|could not|can't|cannot|"
    r"doesn't match|invalid|unable|timed? ?out",
    re.IGNORECASE,
)
LINE_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.(\d+) T:(\d+)\s+(\w+) <[^>]*>: ?(.*)$"
)
STAMP_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ T:")

_REDACT = [
    (re.compile(r"(/(?:live|movie|series)/)([^/?\s]+)(/?)([^/?\s]*)", re.I),
     lambda m: m.group(1) + "***" + m.group(3) + ("***" if m.group(4) else "")),
    (re.compile(r"(?i)\b(password|pwd|pass|username|user|token|api_?key)=([^&\s]+)"), r"\1=***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{10,}"), "***"),
]

_session = {}


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"{LOG_PREFIX} {message}", level)


def redact(text):
    for pattern, repl in _REDACT:
        text = pattern.sub(repl, text)
    return text


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _iso(epoch=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch if epoch else time.time()))


def _addon_version(addon_id):
    try:
        return xbmcaddon.Addon(addon_id).getAddonInfo("version")
    except Exception:
        return None


def device_key():
    """Stable, filename-safe name for this device: friendly name plus a
    short random id persisted on first use (two devices can share a
    friendly name)."""
    try:
        with open(DEVICE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        pass
    name = xbmc.getInfoLabel("System.FriendlyName") or "kodi"
    name = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")[:30] or "kodi"
    key = f"{name}-{hashlib.sha1(os.urandom(16)).hexdigest()[:4]}"
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(DEVICE_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except Exception:
        pass
    return key


def device_info():
    return {
        "key": device_key(),
        "name": xbmc.getInfoLabel("System.FriendlyName"),
        "os": xbmc.getInfoLabel("System.OSVersionInfo"),
        "kodi": xbmc.getInfoLabel("System.BuildVersion"),
        "versions": {
            "service.iptvhelperfixes": _addon_version("service.iptvhelperfixes"),
            "plugin.video.xstream-player": _addon_version("plugin.video.xstream-player"),
            "skin.bingie": _addon_version("skin.bingie"),
            "plugin.video.tmdb.bingie.helper": _addon_version("plugin.video.tmdb.bingie.helper"),
        },
    }


def _load_state():
    state = _read_json(STATE_FILE, {}) or {}
    state.setdefault("offset", 0)
    state.setdefault("head", "")
    state.setdefault("errors", {})
    state.setdefault("crashes", [])
    return state


def _save_state(state):
    errors = state["errors"]
    if len(errors) > MAX_ERRORS:
        keep = sorted(errors.items(), key=lambda kv: kv[1]["last"], reverse=True)[:MAX_ERRORS]
        state["errors"] = dict(keep)
    state["crashes"] = state["crashes"][-MAX_CRASHES:]
    _write_json(STATE_FILE, state)


def _is_interesting(level, msg):
    if "[diag]" in msg:
        return False
    if level in ("error", "fatal"):
        return True
    if any(o in msg for o in OURS):
        return level == "warning" or bool(KEYWORDS.search(msg))
    return False


def _signature(text):
    t = re.sub(r"0x[0-9a-fA-F]+", "0x", text)
    t = re.sub(r"\d+", "N", t)
    t = re.sub(r"\s+", " ", t)
    return hashlib.sha1(t[:400].encode("utf-8", "replace")).hexdigest()[:12]


def _parse_events(lines):
    """Interesting lines -> events; consecutive lines from the same thread
    within a second of each other (a traceback) are merged into one."""
    events = []
    last = None
    for raw in lines:
        m = LINE_RE.match(raw)
        if not m:
            continue
        stamp, _frac, thread, level, msg = m.groups()
        level = level.lower()
        if not _is_interesting(level, msg):
            last = None
            continue
        try:
            epoch = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            epoch = 0
        if last and last["thread"] == thread and 0 <= epoch - last["epoch"] <= 1:
            last["text"] += "\n" + msg
            last["epoch"] = epoch
            if level in ("error", "fatal"):
                last["level"] = level
        else:
            last = {"stamp": stamp, "thread": thread, "level": level, "text": msg, "epoch": epoch}
            events.append(last)
    return events


def scan_log(path, state):
    """Scan new bytes of a Kodi log file for errors, updating state in
    place. Offsets are tracked per file; a changed first line (log rotated
    at a new launch) restarts from the top."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0
    with open(path, "rb") as f:
        head = f.readline()[:80].decode("utf-8", "replace")
        offset = state.get("offset", 0)
        if head != state.get("head") or offset > size:
            offset = 0
        state["head"] = head
        start = max(offset, size - MAX_SCAN_BYTES)
        f.seek(start)
        data = f.read(size - start)
    cut = data.rfind(b"\n")
    if cut < 0:
        return 0
    state["offset"] = start + cut + 1
    lines = data[: cut + 1].decode("utf-8", "replace").splitlines()
    found = 0
    for ev in _parse_events(lines):
        text = redact(ev["text"])[:MAX_SAMPLE]
        sig = _signature(text)
        entry = state["errors"].get(sig)
        if entry:
            entry["count"] += 1
            entry["last"] = ev["stamp"]
            entry["level"] = ev["level"]
        else:
            state["errors"][sig] = {
                "first": ev["stamp"],
                "last": ev["stamp"],
                "count": 1,
                "level": ev["level"],
                "sample": text,
            }
        found += 1
    return found


def _tail_info(path, count=40):
    """(timestamp of the last timestamped line, last `count` lines redacted)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 24000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None, []
    last_stamp = None
    for line in reversed(lines):
        m = STAMP_RE.match(line)
        if m:
            last_stamp = m.group(1)
            break
    tail = [redact(line)[:300] for line in lines[-count:]]
    return last_stamp, tail


def _mac_crash_report(since_epoch):
    """Newest macOS crash report for Kodi written after the previous
    session started: exception type, signal and top frames of the crashing
    thread. Best effort; macOS only."""
    folder = os.path.expanduser("~/Library/Logs/DiagnosticReports")
    try:
        files = [
            os.path.join(folder, n)
            for n in os.listdir(folder)
            if n.startswith("Kodi") and n.endswith(".ips")
        ]
        files = [p for p in files if os.path.getmtime(p) >= since_epoch - 60]
        if not files:
            return None
        path = max(files, key=os.path.getmtime)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            body = json.loads(f.read().split("\n", 1)[1])
        out = {
            "file": os.path.basename(path),
            "exception": body.get("exception"),
            "termination": body.get("termination"),
        }
        threads = body.get("threads") or []
        idx = body.get("faultingThread")
        if isinstance(idx, int) and idx < len(threads):
            images = body.get("usedImages") or []
            frames = []
            for fr in (threads[idx].get("frames") or [])[:10]:
                img = images[fr["imageIndex"]].get("name") if fr.get("imageIndex") is not None else None
                frames.append(f"{img or '?'}: {fr.get('symbol') or hex(fr.get('imageOffset', 0))}")
            out["crashing_thread_frames"] = frames
        return out
    except Exception:
        return None


def begin_session():
    """Call once at service start. Records a crash if the previous run never
    closed its session, finishes scanning the previous log, then opens a new
    session."""
    global _session
    state = _load_state()
    old = _read_json(SESSION_FILE)
    try:
        scan_log(OLD_LOG_PATH, state)
    except Exception as e:
        log(f"could not scan previous log: {e}", xbmc.LOGWARNING)

    if old and not old.get("clean"):
        last_log_time, tail = _tail_info(OLD_LOG_PATH)
        crash = {
            "detected": _iso(),
            "session_started": _iso(old.get("started_epoch")),
            "last_heartbeat": _iso(old.get("heartbeat_epoch")),
            "last_log_line_time": last_log_time,
            "ran_for_minutes": round((old.get("heartbeat_epoch", 0) - old.get("started_epoch", 0)) / 60, 1),
            "versions": old.get("versions"),
            "note": "unclean exit: a crash, a force-quit, or the device losing power",
            "log_tail": tail,
        }
        report = _mac_crash_report(old.get("started_epoch", 0))
        if report:
            crash["crash_report"] = report
        state["crashes"].append(crash)
        log(f"previous session ended abnormally (last log line {last_log_time})", xbmc.LOGWARNING)

    state["offset"] = 0
    state["head"] = ""
    _save_state(state)

    now = time.time()
    _session = {
        "started_epoch": now,
        "heartbeat_epoch": now,
        "clean": False,
        "versions": device_info()["versions"],
    }
    _write_json(SESSION_FILE, _session)


def heartbeat():
    if _session:
        _session["heartbeat_epoch"] = time.time()
        try:
            _write_json(SESSION_FILE, _session)
        except OSError:
            pass


def end_session():
    """Call on a normal shutdown so the next start doesn't report a crash."""
    if _session:
        _session["clean"] = True
        _session["ended_epoch"] = time.time()
        _session["heartbeat_epoch"] = _session["ended_epoch"]
        try:
            _write_json(SESSION_FILE, _session)
        except OSError:
            pass


def _build_report(state):
    errors = sorted(state["errors"].values(), key=lambda e: e["last"], reverse=True)
    report = {
        "device": device_info(),
        "current_session_started": _iso(_session.get("started_epoch")) if _session else None,
        "crashes": state["crashes"],
        "errors": errors,
    }
    return report


DIAG_GIST_DESCRIPTION = "IPTV Helper Fixes error reports (managed by IPTV Helper Fixes -- do not delete)"


def _upload_target(svc):
    """(token, gist_setting, description) to upload to, or None. A build for
    other people carries a dedicated diagnostics token (diag_token) that
    reports into its own gist, separate from the watch-progress sync; without
    one, the owner's own devices keep using the sync gist as before. The
    "Send error reports" setting turns it all off."""
    if svc.getSetting("diag_enabled").lower() == "false":
        return None
    diag_token = svc.getSetting("diag_token").strip()
    if diag_token:
        return diag_token, "diag_gist_id", DIAG_GIST_DESCRIPTION
    if svc.getSetting("github_sync_enabled").lower() != "true":
        return None
    token = svc.getSetting("github_sync_token").strip()
    return (token, "github_sync_gist_id", None) if token else None


def upload(state):
    """Mirror this device's report into a gist as diag_<device>.json, only
    when it changed and only if a diagnostics or sync token is configured."""
    import github_sync  # same folder; imported lazily so a failure here can't break startup

    svc = xbmcaddon.Addon()
    target = _upload_target(svc)
    if not target:
        return
    token, gist_setting, description = target
    report = _build_report(state)
    content = json.dumps(report, ensure_ascii=False, indent=1)
    while len(content) > UPLOAD_LIMIT and report["errors"]:
        report["errors"] = report["errors"][: max(0, len(report["errors"]) // 2)]
        content = json.dumps(report, ensure_ascii=False, indent=1)
    digest = hashlib.sha1(
        json.dumps({"c": report["crashes"], "e": report["errors"]}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if digest == state.get("uploaded_hash"):
        return
    saved = svc.getSetting(gist_setting).strip()
    gist_id = github_sync._find_or_create_gist(token, saved, description)
    if not gist_id:
        return
    if gist_id != saved:
        svc.setSetting(gist_setting, gist_id)
    github_sync._github_request(
        "PATCH", f"/gists/{gist_id}", token,
        data={"files": {f"diag_{device_key()}.json": {"content": content}}},
    )
    state["uploaded_hash"] = digest
    log(f"uploaded diagnostics ({len(report['errors'])} error types, {len(report['crashes'])} crashes)")


def run_cycle():
    """One pass: scan the live log, save, and upload if anything changed."""
    state = _load_state()
    try:
        scan_log(LOG_PATH, state)
    except Exception as e:
        log(f"log scan failed: {e}", xbmc.LOGWARNING)
    try:
        upload(state)
    except Exception as e:
        log(f"upload failed: {e}", xbmc.LOGWARNING)
    _save_state(state)
