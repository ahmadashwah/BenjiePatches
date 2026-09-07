# Kodi + Bingie + XStream Player — Full Replication Guide

Everything below is what it actually took to get from "fresh Kodi install" to
the current working state: click a movie/show in Discover (or search for
one), have it automatically search your Xtream Codes IPTV catalog, show clean
matching results, and play — including specific episodes, drilled all the way
down automatically.

This supersedes the earlier version of this report — several bugs were found
and fixed *after* the original "it works" point, so follow this version if
starting fresh.

---

## Phase 0 — Install Kodi itself

Download and install Kodi normally for the target platform (kodi.tv, or the
Play Store / App Store on Android/Android TV/Fire TV/iOS). Nothing below
applies until this exists.

---

## Phase 1 — Install the skin and add-ons

1. Settings → File Manager → Add source → enter the Bingie skin repository's
   zip/URL (use whatever source you trust for this).
2. Settings → Add-ons → Install from zip file → install the repository, then
   Install from repository → install the **Bingie** skin. This also pulls in
   its required companion add-on, **`plugin.video.tmdb.bingie.helper`**
   ("TMDb Bingie Helper") — the thing that renders "Discover."
3. Settings → Interface → Skin → set skin to **Bingie**.
4. Repeat the zip-install steps for **XStream Player**
   (`plugin.video.xstream-player`, by Pesicp) from its own repository.

## Phase 2 — Configure your Xtream Codes account

1. Add-ons → Video Add-ons → XStream Player → Tools → Settings → Profiles.
2. Enable Profile 1, enter your Xtream Codes server URL / username /
   password.
3. Back out and run **Load TV, Movies, Series** to build the local cache.
   This can take a while the first time — it's a large catalog.

At this point Discover and XStream Player are two disconnected things. Every
phase below wires them together and fixes bugs that surfaced along the way.

---

## Phase 3 onward — two ways to apply the fixes

**Option A — Install the add-on (recommended, works on literally any device):**

In Kodi, add `https://ahmadashwah.github.io/BenjiePatches/` as a source
(Settings → File Manager → Add source), then **Settings → Add-ons → Install
from zip file** → pick that source → select the current zip listed on the
page (the filename includes the version number, e.g.
`service.iptvhelperfixes107.zip`, so each release has its own unique
filename and never gets served stale from a cache).

That's it — no computer, no command prompt, no keyboard needed, works
identically on Android TV, Fire TV, Google TV, Windows, macOS, or Linux,
because it runs on Kodi's own built-in Python instead of an external one.
It's a background service that checks itself every time Kodi starts:

- Installs/updates the player config (Phase 3 below).
- If XStream Player is installed, vendors the `defusedxml` library into its
  lib folder. XStream Player's own `epg.py` already tries to use
  `defusedxml` for safe XML parsing and only falls back to a much stricter
  (and, it turns out, overly strict) parser if that library isn't present —
  that fallback rejects any XMLTV guide feed containing a standard
  `<!DOCTYPE>` declaration, which is normal and present in nearly every real
  provider's feed, so the EPG/guide data (and PVR search, which searches
  guide data) stayed permanently empty. Adding the library fixes this
  without touching any of XStream Player's own code.
- If XStream Player is installed and is exactly version 2.1.5, replaces its
  `addon.py` with the pre-patched copy bundled in the add-on (Phases 4–6
  below), keeping a timestamped backup of whatever was there first. If the
  installed version doesn't match, it logs a warning and does nothing to
  that file, rather than risk corrupting a different version's code.
- Sets XStream Player as the default player (no "which app"/"which action"
  chooser dialog every time you press Play).
- Adds a **Live TV** shortcut to the Bingie skin's home menu (native Kodi
  PVR channel list) if the skin's shortcuts are already set up and it isn't
  there yet.
- Reroutes the Bingie skin's main search box to XStream Player's own
  catalog search (movies, series, and live channels) whenever the typed
  term contains Arabic script, since TMDb rarely has Arabic-language IPTV
  content indexed at all — searching there could never find it regardless
  of the term. English/Latin search goes to TMDb exactly as before. This
  patch matches the skin's search file by exact content, not by version
  number, so it safely does nothing instead of risking corruption if a
  future skin update changes that section.

Every check is idempotent — it compares content first and only writes when
something's actually different — and it repeats every 5 minutes for as long
as Kodi is running, not just once at startup. That's what lets it
immediately re-fix itself if something overwrites a file it manages later
(an XStream Player update, or script.skinshortcuts resyncing its own
shortcuts file and reverting the Live TV entry), instead of only catching it
on the next reboot.

**Option B — Manual / Python script (desktop only):** the sections below
document exactly what the add-on does and why, in case you want to apply
individual patches by hand, understand the reasoning, or run
`setup_xstream_fixes.py` directly on a Mac/Windows/Linux machine instead of
installing the add-on.

---

## Phase 3 — Player config file (wires Discover → XStream Player search)

**File:** `<Kodi userdata>/addon_data/plugin.video.tmdb.bingie.helper/players/autogen.plugin.video.xstream-player.json`
(macOS: `~/Library/Application Support/Kodi/userdata/addon_data/plugin.video.tmdb.bingie.helper/players/`)

Create the `players/` folder if it doesn't exist, and put this file in it:

```json
{
    "name": "My IPTV Player",
    "plugin": "plugin.video.xstream-player",
    "priority": 100,
    "is_resolvable": "true",
    "assert": {
        "play_movie": ["title"],
        "search_movie": ["title"],
        "play_episode": ["showname", "season", "episode"],
        "search_episode": ["showname", "season", "episode"]
    },
    "play_movie": [
        "plugin://plugin.video.xstream-player/?mode=search_global&query={title_url}&stype=movie&profile_num=1",
        {"label": "(?i)^{title}\\s*\\({year}\\)", "dialog": "Auto"}
    ],
    "search_movie": [
        "plugin://plugin.video.xstream-player/?mode=search_global&query={title_url}&stype=movie&profile_num=1",
        {"label": "(?i)^{title}\\s*\\({year}\\)", "dialog": "Auto"}
    ],
    "play_episode": [
        "plugin://plugin.video.xstream-player/?mode=search_global&query={showname_url}&stype=series&profile_num=1",
        {"label": "(?i)^{showname}\\s*\\({year}\\)", "dialog": "Auto"},
        {"season": "^{season}$", "dialog": "Auto"},
        {"label": "(?i).*S0*{season}E0*{episode}\\b.*", "return": "true", "dialog": "Auto"}
    ],
    "search_episode": [
        "plugin://plugin.video.xstream-player/?mode=search_global&query={showname_url}&stype=series&profile_num=1",
        {"label": "(?i)^{showname}\\s*\\({year}\\)", "dialog": "Auto"},
        {"season": "^{season}$", "dialog": "Auto"},
        {"label": "(?i).*S0*{season}E0*{episode}\\b.*", "return": "true", "dialog": "Auto"}
    ]
}
```

**Why it's built this way:**
- `mode=search_global` is XStream Player's real internal search route (found
  by reading its own source — `resources/lib/addon.py` — there's no public
  API doc). It takes `query`, `stype` (`movie`/`series`), and `profile_num`
  directly, no on-screen typing.
- A route that looks like the obvious guess but does **not** exist:
  `mode=search`. It produces a Kodi log error and silently fails.
- The trailing dialog step (`{"dialog": "true"}` or `{"label": ..., "dialog": "Auto"}`)
  on the movie steps is required. The helper add-on only substitutes
  placeholders like `{title_url}` when there's a step *after* the URL — a
  single-element action list passes straight through unmodified, so it would
  literally search for a movie named `{title_url}` and always find nothing.
- The `^{title}\s*\({year}\)` / `^{showname}\s*\({year}\)` anchoring exists
  because the plain substring search can return more than one real match —
  e.g. a provider carrying both the 2005 US "The Office" and the 2024
  Australian reboot under the same base name. Without the year check, a
  naive regex matching just the name will silently grab whichever one comes
  first in the results, which is wrong roughly as often as it's right.
  Anchoring on the exact title+year auto-plays the correct one when it's
  unique, and only falls back to the picker when it isn't.
- The `play_episode`/`search_episode` chain is more involved because a naive
  version only matches the *show*, dumping you into XStream Player's own
  season/episode browser to find the episode by hand. The chain drills
  further: match the show name+year → match the season by its real season
  number (XStream Player does set this correctly) → match the specific
  episode by a `S0xE0x` pattern against its title text, because XStream
  Player does **not** set a real episode-number field on episode items
  (checked directly — only the season number is exposed as real metadata).
  Once matched, it plays immediately instead of stopping at a browse screen.

Also: once picked from the "Play with…" dialog once, TMDbHelper should offer
to remember this as default so it doesn't ask every time. If not, set it
manually under **Add-ons → My add-ons → TMDb Bingie Helper → Configure →
default_player_movies / default_player_episodes**.

---

## Phase 4 — Patch: series search returns an empty ID (bug in XStream Player)

**File:** `<Kodi addons>/plugin.video.xstream-player/resources/lib/addon.py`, inside `unified_search()`.

Change:
```python
sid = str(s.get("stream_id", ""))
```
to:
```python
sid = str(s.get("stream_id") or s.get("series_id") or "")
```

**Why:** confirmed by inspecting the addon's own cached catalog data — series
entries carry their ID under `series_id`, not `stream_id`. The unpatched line
always produced an empty ID for series search results, so the follow-up
season lookup silently failed and showed "0 Season."

---

## Phase 5 — Patch: clean up provider name prefixes (movies + series)

Your provider prefixes every catalog name with a source/language/quality tag
— e.g. `"AR-SUBS: Legend (2015)"`, `"4K-AR: Some Movie"`. Fixed centrally so
every screen benefits, not just search.

**File:** same `addon.py`. Near the top (after `pm = ProfileManager(addon)`), add:

```python
# Provider catalog names are prefixed with a source/language/quality tag,
# e.g. "AR-SUBS: Legend (2015)" or "4K-AR: Some Movie" — strip it for display.
# Uppercase-only so real titles like "Spider-Man: Far From Home" aren't touched.
_PROVIDER_PREFIX_RE = re.compile(r"^[A-Z0-9\-]{1,15}:\s*")
```

Inside `_get_cached_xtream_streams()` — the one central function every screen
goes through to get movie/series data — right before its return statements:

```python
if stype in ("movie", "series"):
    for s in data:
        raw_name = s.get("name", "")
        m = _PROVIDER_PREFIX_RE.match(raw_name)
        if m:
            s["provider_tag"] = m.group(0).rstrip(": ").strip()
            cleaned = raw_name[m.end():].strip()
            if cleaned:
                s["name"] = cleaned
        else:
            s["provider_tag"] = ""
```

**Why this location:** cleaning at the one shared data-loading function means
every screen — search, category browsing, favorites, the custom IPTV Movies
grid — gets clean names automatically, with no per-screen patching needed.

**Why the regex is uppercase-only:** the first version matched any
`Word:`-shaped prefix, which incorrectly stripped the start of real titles
like `"Spider-Man: Far From Home"` and `"Superman: Red Son"` — their own
colon looked like a tag. Verified against the *entire* real catalog
(52,000+ titles): the uppercase-only version has **zero** false positives
while still cleaning 98.6% of movies and 99.2% of series that do have a
provider tag.

**Stripping the tag everywhere has a side effect worth knowing:** the "Select
Item" picker (shown when a search matches more than one item) used to show
the tag as part of the title, which — confusingly — was the only thing
telling apart otherwise-identical-looking entries (e.g. an `AR-SUBS` copy vs
an `NF` copy of the same movie). Fixed by keeping the tag in a separate
`s["provider_tag"]` field (set alongside the cleaned name in
`_get_cached_xtream_streams()`) and appending it back **only** to the label
shown in the picker (in `unified_search()`'s movie/series item-building code)
— e.g. `"The Office (2005)  [AR-SUBS]"` — while every other screen (info
dialogs, category browsing, etc.) still shows the plain clean title.

**Episode titles need a separate fix** — they come from a different API call
(`get_xtream_series_info`), not the function patched above, so they carry
their own copy of the same prefix untouched by it.

In `xtream_season()`:
```python
for ep in eps:
    ep_id = str(ep.get("id", ""))
    title = ep.get("title") or _t(30542, ep.get("episode_num", "?"))
    title = _PROVIDER_PREFIX_RE.sub("", title, count=1).strip() or title   # ADD THIS LINE
    label = title
```

And in the "Up Next" next-episode lookup (search for `next_ep.get("title")`):
```python
next_title = next_ep.get("title") or _t(30542, next_ep.get("episode_num", "?"))
next_title = _PROVIDER_PREFIX_RE.sub("", next_title, count=1).strip() or next_title   # ADD THESE TWO LINES
```

---

## Phase 6 — Patch: two separate EPG notification bugs

Symptom: an "XStream Player: EPG data could not be loaded" toast pops up
while browsing or playing *movies/series* — completely unrelated to Live TV.

Both are the same mistake in two different functions: they unconditionally
try to fetch the Live TV program guide regardless of what type of content is
being requested.

**Fix 1 — inside `xtream_streams()`** (used by category browsing):
```python
# before
epg = EPG(addon, profile_num=pnum)
epg.load()
if epg.is_refreshing:
    _log("EPG background refresh in progress - showing cached/stale data")

# after
if stype == "live":
    epg = EPG(addon, profile_num=pnum)
    epg.load()
    if epg.is_refreshing:
        _log("EPG background refresh in progress - showing cached/stale data")
```

**Fix 2 — inside `unified_search()`** (used by `search_global`, which the
player config in Phase 3 calls on every play/search — this is the one that
fires during the episode-play chain specifically):
```python
# before
epg = EPG(addon, profile_num=pm.active)
epg.load()
show_epg = _epg_enabled()

# after
epg = None
show_epg = False
if stype is None or stype == "live":
    epg = EPG(addon, profile_num=pm.active)
    epg.load()
    show_epg = _epg_enabled()
```

There may be further occurrences of this same pattern elsewhere in the file
(`grep -n "EPG(addon" addon.py` turns up over a dozen call sites total) — if
the notification reappears on a different screen, that's most likely another
unaudited instance of the same bug.

---

## Optional — a plain "IPTV Movies" shortcut (no custom screen)

Bingie's own "Movies" hub only shows TMDb-curated rows, not your provider's
actual VOD categories. `movies_menu()` in XStream Player already lists every
category your provider defines (`xtream_categories("movie", profile_num)`),
so the simplest way to reach it is a home-menu shortcut straight into that
native screen — no custom skin window needed:

**File:** `<Kodi userdata>/addon_data/script.skinshortcuts/skin.bingie-mainmenu.DATA.xml`
```xml
<shortcut>
	<defaultID />
	<label>IPTV Movies</label>
	<label2>Video Add-On</label2>
	<icon>DefaultShortcut.png</icon>
	<thumb>thumb</thumb>
	<action>ActivateWindow(Videos,"plugin://plugin.video.xstream-player/?mode=movies_menu&amp;profile_num=1",return)</action>
	</shortcut>
```

A fancier Netflix-style category browser (custom skin screen, poster grid,
etc.) was prototyped and then deliberately rolled back — worth reconsidering
as its own separate decision rather than folding into this baseline
replication path. If picked back up later, the design notes worth keeping in
mind: XStream Player's category list runs to ~148 categories, real stacked
"Netflix rows" for all of them needs Kodi's more advanced nested-widget
pattern (meaningfully more complex than a single reactive preview panel), and
a poster grid's focus highlight needs to be drawn *around* a slightly inset
poster, not behind a full-opacity one, or it's invisible even when focus is
moving correctly.

---

## Optional — Arabic keyboard input for search

Not a code change — an existing but disabled skin setting, plus a Kodi core
feature that already exists:

1. `Settings → Interface → Regional → Keyboard layouts` → enable **Arabic**
   (Kodi ships this natively as `system/keyboardlayouts/arabic.xml`).
2. `Settings → Skin Settings → Home screen layout` → scroll to the **Search**
   section → enable **"Enable option for a complete keyboard."**
3. On the Search screen, press **Up** from the on-screen keyboard grid — this
   opens Kodi's real native keyboard (which supports the layout switch from
   step 1), instead of Bingie's custom Latin-only on-screen grid.

---

## Result, end to end

- Search or Discover a movie by (roughly) its English/official title → pick
  "XStream Player" → picker lists matching results from your actual catalog,
  clean titles, real posters → play.
- Same for a specific episode of a show — picks the show, then the season,
  then the exact episode automatically, and plays it directly.
