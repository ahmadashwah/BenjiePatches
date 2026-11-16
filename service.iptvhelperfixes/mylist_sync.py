# -*- coding: utf-8 -*-
"""Bengie: My List across devices, through the same private gist as the
watch-progress sync (github_sync.py).

My List shows two stores, both kept per device: Kodi's Favourites
(favourites.xml, what the long-press "Add to favourites" writes) and XStream
Player's profile favourites (favorites_<n>.json). Neither records when an
item was added or removed, so each device keeps a ledger per store:
{key: {..item.., "present": bool, "timestamp": t}}. Every pass it

1. notes local changes since the last pass (an item that appeared: present,
   now; an item that disappeared: absent, now),
2. merges its ledger with the gist's copy, newest timestamp per item winning
   (so removals travel as well as additions),
3. makes the local store match: adds what is present and missing, removes
   what is absent and still there.

Kodi's favourites are changed through Kodi (JSON-RPC Favourites.AddFavourite,
which adds or, for an existing one, removes), never by editing the file under
Kodi; a removal is checked afterwards and undone if Kodi added instead.
XStream Player's file is plain JSON that it reads on every call.
"""

import json
import os
import re
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcvfs

TOMBSTONE_DAYS = 90
SERVICE_DATA = "special://profile/addon_data/service.iptvhelperfixes/"
KODI_FAVOURITES = "special://profile/favourites.xml"


def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[IPTV Helper Fixes] [mylist] {message}", level)


def _rpc(method, **params):
    return json.loads(xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})))


def _read_json(path, default):
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


# ------------------------------------------------------------------ stores

class KodiFavourites:
    """favourites.xml entries that play something or open a folder."""

    name = "mylist_kodi"

    def __init__(self):
        self.path = xbmcvfs.translatePath(KODI_FAVOURITES)

    @staticmethod
    def parse(cmd):
        cmd = (cmd or "").strip()
        m = re.match(r'(?is)^PlayMedia\(\s*"(.*)"\s*(?:,[^"]*)?\)$', cmd) or \
            re.match(r'(?is)^PlayMedia\(\s*([^,"]+?)\s*(?:,[^"]*)?\)$', cmd)
        if m:
            return {"kind": "media", "path": m.group(1)}
        m = re.match(r'(?is)^ActivateWindow\(\s*([^,]+?)\s*,\s*"(.*)"\s*(?:,[^"]*)?\)$', cmd) or \
            re.match(r'(?is)^ActivateWindow\(\s*([^,]+?)\s*,\s*([^,"]+?)\s*(?:,[^"]*)?\)$', cmd)
        if m:
            return {"kind": "window", "window": m.group(1), "path": m.group(2)}
        return None

    def list_local(self):
        out = {}
        try:
            if not os.path.isfile(self.path):
                return out
            for fav in ET.parse(self.path).getroot():
                item = self.parse(fav.text)
                if not item:
                    continue
                item["title"] = fav.get("name", "")
                item["thumb"] = fav.get("thumb", "")
                out[f'{item["kind"]}|{item["path"]}'] = item
        except Exception as e:
            log(f"favourites.xml not readable: {e}", xbmc.LOGWARNING)
            return None
        return out

    @staticmethod
    def _rpc_params(item):
        params = {"title": item.get("title") or " ", "type": item["kind"]}
        if item.get("thumb"):
            params["thumbnail"] = item["thumb"]
        if item["kind"] == "media":
            params["path"] = item["path"]
        else:
            window = str(item.get("window") or "videos")
            params["window"] = "videos" if window in ("10025", "10024") else window
            params["windowparameter"] = item["path"]
        return params

    def add(self, key, item):
        res = _rpc("Favourites.AddFavourite", **self._rpc_params(item))
        if "error" in res:
            log(f"could not add favourite {item.get('title')!r}: {res['error'].get('message')}", xbmc.LOGWARNING)

    def remove(self, key, item):
        before = self.list_local() or {}
        if key not in before:
            return
        _rpc("Favourites.AddFavourite", **self._rpc_params(item))
        after = self.list_local() or {}
        if key in after:
            # Kodi built a slightly different command and added a second copy
            # instead of removing: take that copy back out (same call again).
            log(f"favourite {item.get('title')!r} wasn't removed by Kodi; leaving it.", xbmc.LOGWARNING)
            if len(after) > len(before):
                _rpc("Favourites.AddFavourite", **self._rpc_params(item))


class XStreamFavourites:
    """XStream Player's profile favourites (favorites_<n>.json), all folders."""

    def __init__(self, profile_dir, pnum):
        self.name = f"mylist_xstream_p{pnum}"
        self.path = os.path.join(profile_dir, f"favorites_{pnum}.json")

    def _load(self):
        data = _read_json(self.path, None)
        if data is None and os.path.exists(self.path):
            return None  # unreadable: leave it alone this pass
        if isinstance(data, list):
            data = {"version": 1, "Favorites": data}
        return data if isinstance(data, dict) else {"version": 1, "Favorites": []}

    def list_local(self):
        data = self._load()
        if data is None:
            return None
        out = {}
        for folder, items in data.items():
            if folder == "version" or not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and it.get("id") is not None:
                    out[str(it["id"])] = {"folder": folder, "entry": it}
        return out

    def add(self, key, item):
        data = self._load()
        if data is None:
            return
        folder = item.get("folder") or "Favorites"
        data.setdefault(folder, [])
        if not any(str(i.get("id")) == key for i in data[folder] if isinstance(i, dict)):
            data[folder].append(item.get("entry") or {})
            _write_json(self.path, data)

    def remove(self, key, item):
        data = self._load()
        if data is None:
            return
        changed = False
        for folder, items in list(data.items()):
            if folder == "version" or not isinstance(items, list):
                continue
            kept = [i for i in items if not (isinstance(i, dict) and str(i.get("id")) == key)]
            if len(kept) != len(items):
                data[folder] = kept
                changed = True
        if changed:
            _write_json(self.path, data)


# ------------------------------------------------------------------ ledger

def merge(local, remote):
    """Newest timestamp per key wins; ties keep the local copy."""
    merged = dict(local or {})
    for k, v in (remote or {}).items():
        if not isinstance(v, dict):
            continue
        if k not in merged or v.get("timestamp", 0) > merged[k].get("timestamp", 0):
            merged[k] = v
    return merged


def note_local_changes(ledger, local, seen, now):
    """Items that appeared locally since the last pass become present (now),
    items that disappeared become absent (now)."""
    ledger = dict(ledger)
    for k, item in local.items():
        entry = ledger.get(k)
        if k not in seen and not (entry and entry.get("present")):
            ledger[k] = dict(item, present=True, timestamp=now)
    for k in seen - set(local):
        entry = ledger.get(k)
        if entry and entry.get("present"):
            ledger[k] = dict(entry, present=False, timestamp=now)
    return ledger


def prune(ledger, now):
    limit = now - TOMBSTONE_DAYS * 86400
    return {k: v for k, v in ledger.items() if v.get("present") or v.get("timestamp", 0) >= limit}


def apply(store, ledger, local):
    """Makes the local store match the ledger."""
    for k, entry in ledger.items():
        if entry.get("present") and k not in local:
            store.add(k, entry)
        elif not entry.get("present") and k in local:
            store.remove(k, local[k])


def sync_store(store, remote_ledger, state, now):
    """One store: returns the merged ledger to publish, or None to skip."""
    local = store.list_local()
    if local is None:
        return None
    seen = set(state.get("seen", {}).get(store.name, []))
    ledger_path = os.path.join(xbmcvfs.translatePath(SERVICE_DATA), f"{store.name}.json")
    ledger = _read_json(ledger_path, {})
    ledger = note_local_changes(ledger, local, seen, now)
    merged = prune(merge(ledger, remote_ledger), now)
    apply(store, merged, local)
    after = store.list_local()
    state.setdefault("seen", {})[store.name] = sorted((after if after is not None else local).keys())
    _write_json(ledger_path, merged)
    return merged


def sync_all(token, gist_id, profile_dir, profiles, request, fetch_remote):
    """Runs after the watch-progress sync. request/fetch_remote are
    github_sync's _github_request/_fetch_remote_content."""
    try:
        gist = request("GET", f"/gists/{gist_id}", token)
    except Exception as e:
        log(f"Error fetching gist: {e}", xbmc.LOGERROR)
        return
    remote_files = gist.get("files", {})
    state_path = os.path.join(xbmcvfs.translatePath(SERVICE_DATA), "mylist_seen.json")
    state = _read_json(state_path, {})
    now = time.time()
    stores = [KodiFavourites()] + [XStreamFavourites(profile_dir, p) for p in profiles]
    payload = {}
    for store in stores:
        fname = f"{store.name}.json"
        entry = remote_files.get(fname)
        remote = fetch_remote(entry) if entry else None
        try:
            merged = sync_store(store, remote if isinstance(remote, dict) else {}, state, now)
        except Exception as e:
            log(f"{store.name}: {e}", xbmc.LOGERROR)
            continue
        if merged is not None and merged != remote:
            payload[fname] = {"content": json.dumps(merged, ensure_ascii=False)}
    _write_json(state_path, state)
    if payload:
        try:
            request("PATCH", f"/gists/{gist_id}", token, data={"files": payload})
            log(f"Synced My List ({', '.join(sorted(payload))}).")
        except Exception as e:
            log(f"Error pushing My List: {e}", xbmc.LOGERROR)
