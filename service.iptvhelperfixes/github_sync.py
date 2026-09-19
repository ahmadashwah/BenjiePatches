# -*- coding: utf-8 -*-
"""GitHub Gist-based cross-device sync for XStream Player's watch progress.

Each of the per-profile JSON files XStream Player's history.py keeps
(resume points, watch history, finished markers, watched movies, watched
episodes) gets mirrored into a file of the same name inside one private
Gist, so any other device syncing against the same Gist (same token)
converges on the same data.

Deliberately simple: last-write-wins per entry, using each entry's own
"timestamp" field where one exists. Not a CRDT -- built for a handful of
personal devices syncing every few minutes, not concurrent heavy writers.
"""

import json
import os

import requests
import xbmc
import xbmcaddon
import xbmcvfs

LOG_PREFIX = "[IPTV Helper Fixes]"
GITHUB_API = "https://api.github.com"
GIST_DESCRIPTION = "XStream Player watch progress sync (managed by IPTV Helper Fixes -- do not delete)"
XSTREAM_ADDON_ID = "plugin.video.xstream-player"

# (filename template, merge kind) for each store history.py maintains per
# profile. "{n}" is replaced with the profile number.
SYNCED_FILES = [
    ("resume_points_p{n}.json", "timestamped_dict"),
    ("finished_p{n}.json", "timestamped_dict"),
    ("watch_history_p{n}.json", "history_list"),
    ("watched_movies_p{n}.json", "union_bool"),
    ("watched_episodes_p{n}.json", "union_nested"),
]

HTTP_TIMEOUT = 15


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"{LOG_PREFIX} [sync] {message}", level)


def _xstream_addon():
    try:
        return xbmcaddon.Addon(XSTREAM_ADDON_ID)
    except Exception:
        return None


def _xstream_profile_dir():
    xs = _xstream_addon()
    if not xs:
        return None
    return xbmcvfs.translatePath(xs.getAddonInfo("profile"))


def _github_request(method, path, token, data=None):
    url = f"{GITHUB_API}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "iptvhelperfixes-sync",
    }
    resp = requests.request(method, url, headers=headers, json=data, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def _find_or_create_gist(token, existing_gist_id):
    """Return a gist id to sync against: the saved one if it still
    resolves under this token, else one already created by this add-on
    under this account, else a freshly created private one."""
    if existing_gist_id:
        try:
            _github_request("GET", f"/gists/{existing_gist_id}", token)
            return existing_gist_id
        except Exception:
            log(f"Saved gist id {existing_gist_id} no longer resolves, looking for another.", xbmc.LOGWARNING)

    try:
        gists = _github_request("GET", "/gists?per_page=100", token)
        for g in gists:
            if g.get("description") == GIST_DESCRIPTION:
                return g["id"]
    except Exception as e:
        log(f"Error listing gists: {e}", xbmc.LOGERROR)
        return None

    try:
        created = _github_request(
            "POST",
            "/gists",
            token,
            data={
                "description": GIST_DESCRIPTION,
                "public": False,
                "files": {".xstream-sync": {"content": "Managed by IPTV Helper Fixes. Safe to ignore."}},
            },
        )
        log("Created new private gist for sync.")
        return created["id"]
    except Exception as e:
        log(f"Error creating gist: {e}", xbmc.LOGERROR)
        return None


def _load_local(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_local(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _merge_timestamped_dict(local, remote):
    """{key: {..., "timestamp": t}} -- newer timestamp per key wins."""
    local = local or {}
    remote = remote or {}
    merged = dict(local)
    for k, v in remote.items():
        if k not in merged or v.get("timestamp", 0) > merged[k].get("timestamp", 0):
            merged[k] = v
    return merged


def _merge_history_list(local, remote, max_items=50):
    """List of {..., "name", "stype", "timestamp"} -- dedupe by
    (name, stype), newer timestamp wins, most recent first."""
    local = local or []
    remote = remote or []
    by_key = {}
    for entry in local + remote:
        key = (entry.get("name"), entry.get("stype"))
        existing = by_key.get(key)
        if not existing or entry.get("timestamp", 0) > existing.get("timestamp", 0):
            by_key[key] = entry
    merged = sorted(by_key.values(), key=lambda e: e.get("timestamp", 0), reverse=True)
    return merged[:max_items]


def _merge_union_bool(local, remote):
    """{id: true} -- once watched anywhere, watched everywhere. These
    entries carry no timestamp, so manually un-marking watched on one
    device won't reliably propagate -- an accepted tradeoff, since that's
    a rare manual action compared to marking things watched."""
    merged = dict(remote or {})
    merged.update(local or {})
    return merged


def _merge_union_nested(local, remote):
    """{series_id: {season: [episode_ids]}} -- union per season, same
    append-only tradeoff as _merge_union_bool."""
    local = local or {}
    remote = remote or {}
    merged = {}
    for series_id in set(local) | set(remote):
        merged[series_id] = {}
        l_seasons = local.get(series_id, {})
        r_seasons = remote.get(series_id, {})
        for season in set(l_seasons) | set(r_seasons):
            merged[series_id][season] = sorted(
                set(l_seasons.get(season, [])) | set(r_seasons.get(season, []))
            )
    return merged


_MERGERS = {
    "timestamped_dict": _merge_timestamped_dict,
    "history_list": _merge_history_list,
    "union_bool": _merge_union_bool,
    "union_nested": _merge_union_nested,
}


def _resume_finished_consistency_pass(merged_resume, merged_finished):
    """resume_points and finished are meant to be mutually exclusive per
    key (a title is either still in progress or finished, never both).
    Merging the two files independently can violate that when one device
    finished something the other still has an older in-progress entry
    for -- resolve any key present in both by keeping only the newer
    side's copy."""
    shared_keys = set(merged_resume) & set(merged_finished)
    for key in shared_keys:
        r_ts = merged_resume[key].get("timestamp", 0)
        f_ts = merged_finished[key].get("timestamp", 0)
        if f_ts >= r_ts:
            merged_resume.pop(key, None)
        else:
            merged_finished.pop(key, None)
    return merged_resume, merged_finished


def _fetch_remote_content(entry):
    content = entry.get("content", "")
    if entry.get("truncated"):
        try:
            resp = requests.get(entry["raw_url"], timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            content = resp.text
        except Exception as e:
            log(f"Error fetching truncated gist file: {e}", xbmc.LOGERROR)
            return None
    if not content:
        return None
    try:
        return json.loads(content)
    except Exception:
        return None


def sync_profile(pnum, token, gist_id, profile_dir):
    try:
        gist = _github_request("GET", f"/gists/{gist_id}", token)
    except Exception as e:
        log(f"Error fetching gist for profile {pnum}: {e}", xbmc.LOGERROR)
        return
    remote_files = gist.get("files", {})

    local_data = {}
    remote_data = {}
    for fname_tmpl, _kind in SYNCED_FILES:
        fname = fname_tmpl.format(n=pnum)
        local_data[fname] = _load_local(os.path.join(profile_dir, fname))
        remote_entry = remote_files.get(fname)
        remote_data[fname] = _fetch_remote_content(remote_entry) if remote_entry else None

    merged = {}
    for fname_tmpl, kind in SYNCED_FILES:
        fname = fname_tmpl.format(n=pnum)
        merged[fname] = _MERGERS[kind](local_data[fname], remote_data[fname])

    resume_name = f"resume_points_p{pnum}.json"
    finished_name = f"finished_p{pnum}.json"
    merged[resume_name], merged[finished_name] = _resume_finished_consistency_pass(
        merged[resume_name], merged[finished_name]
    )

    gist_files_payload = {}
    for fname_tmpl, _kind in SYNCED_FILES:
        fname = fname_tmpl.format(n=pnum)
        if merged[fname] != local_data[fname]:
            _save_local(os.path.join(profile_dir, fname), merged[fname])
        new_content = json.dumps(merged[fname], ensure_ascii=False)
        old_remote_content = (
            json.dumps(remote_data[fname], ensure_ascii=False)
            if remote_data.get(fname) is not None
            else None
        )
        if new_content != old_remote_content:
            gist_files_payload[fname] = {"content": new_content}

    if gist_files_payload:
        try:
            _github_request("PATCH", f"/gists/{gist_id}", token, data={"files": gist_files_payload})
        except Exception as e:
            log(f"Error pushing merged data to gist for profile {pnum}: {e}", xbmc.LOGERROR)
            return
        log(f"Synced profile {pnum} watch progress.")


def run_sync():
    svc = xbmcaddon.Addon()
    enabled = svc.getSetting("github_sync_enabled").lower() == "true"
    if not enabled:
        return

    xs = _xstream_addon()
    if not xs:
        log("Sync enabled but XStream Player isn't installed -- skipping.", xbmc.LOGWARNING)
        return

    token = svc.getSetting("github_sync_token").strip()
    if not token:
        log("Sync enabled but no GitHub token set -- skipping.", xbmc.LOGWARNING)
        return

    profile_dir = _xstream_profile_dir()
    if not profile_dir or not os.path.isdir(profile_dir):
        log("XStream Player profile folder not found yet -- skipping this pass.", xbmc.LOGWARNING)
        return

    saved_gist_id = svc.getSetting("github_sync_gist_id").strip()
    gist_id = _find_or_create_gist(token, saved_gist_id)
    if not gist_id:
        log("Could not resolve a gist to sync against -- skipping this pass.", xbmc.LOGERROR)
        return
    if gist_id != saved_gist_id:
        svc.setSetting("github_sync_gist_id", gist_id)

    for pnum in range(1, 11):
        if xs.getSetting(f"profile_{pnum}_enabled") != "true":
            continue
        try:
            sync_profile(pnum, token, gist_id, profile_dir)
        except Exception as e:
            log(f"Error syncing profile {pnum}: {e}", xbmc.LOGERROR)
