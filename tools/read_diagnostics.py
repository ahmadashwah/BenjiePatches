#!/usr/bin/env python3
"""Print every device's crash/error report from the sync gist.

Usage:  python3 tools/read_diagnostics.py [--full] [--device NAME]

The GitHub token is read from the GITHUB_TOKEN environment variable, or, on a
Mac with Kodi installed, from the IPTV Helper Fixes add-on settings. Nothing
is written anywhere; this only reads the gist.
"""
import json
import os
import re
import sys
import urllib.request

KODI_SETTINGS = os.path.expanduser(
    "~/Library/Application Support/Kodi/userdata/addon_data/service.iptvhelperfixes/settings.xml"
)


def token():
    t = (os.environ.get("BENJIE_DIAG_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if t:
        return t
    try:
        m = re.search(r'id="github_sync_token"[^>]*>([^<]+)<', open(KODI_SETTINGS, encoding="utf-8").read())
        return m.group(1).strip() if m else ""
    except OSError:
        return ""


def api(path, tok):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "diag-reader"},
    )
    return json.load(urllib.request.urlopen(req, timeout=20))


def main():
    full = "--full" in sys.argv
    only = sys.argv[sys.argv.index("--device") + 1] if "--device" in sys.argv else None
    tok = token()
    if not tok:
        sys.exit("No GitHub token: set GITHUB_TOKEN or enable sync in the add-on settings.")
    gist = next(
        (g for g in api("/gists?per_page=100", tok)
         if "error reports" in (g.get("description") or "") or "watch progress sync" in (g.get("description") or "")),
        None,
    )
    if not gist:
        sys.exit("No diagnostics gist found for this token.")
    files = api(f"/gists/{gist['id']}", tok)["files"]
    reports = {n: f for n, f in files.items() if n.startswith("diag_")}
    if not reports:
        sys.exit("No diagnostics uploaded yet.")
    for name, f in sorted(reports.items()):
        if only and only not in name:
            continue
        content = f.get("content")
        if f.get("truncated"):
            content = urllib.request.urlopen(f["raw_url"], timeout=20).read().decode("utf-8")
        r = json.loads(content)
        d = r["device"]
        print(f"\n=== {d['name']}  [{d['key']}]  {d.get('os','')}  Kodi {d.get('kodi','')}")
        print("    versions:", ", ".join(f"{k.split('.')[-1]} {v}" for k, v in d["versions"].items() if v))
        print(f"    CRASHES / unclean exits: {len(r['crashes'])}")
        for c in r["crashes"][-10:]:
            print(f"      - last log line {c.get('last_log_line_time')}  (ran ~{c.get('ran_for_minutes')} min, detected {c['detected']})")
            if c.get("crash_report"):
                cr = c["crash_report"]
                print(f"        macOS report: {cr.get('file')}  {cr.get('exception')}")
                for fr in (cr.get("crashing_thread_frames") or [])[:5]:
                    print("          ", fr)
            if full:
                print("        log tail:\n          " + "\n          ".join(c.get("log_tail", [])[-15:]))
        print(f"    ERROR TYPES: {len(r['errors'])}")
        for e in r["errors"][: (50 if full else 12)]:
            first = e["sample"].splitlines()[0][:150]
            print(f"      {e['count']:>5}x  last {e['last']}  [{e['level']}] {first}")


if __name__ == "__main__":
    main()
