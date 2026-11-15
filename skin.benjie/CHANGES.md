# Changes from Bingie 2.0.2

## 2.0.2.6 (2026-11-14)

- `1080i/DialogExtendedProgressBar.xml`: Kodi's "PVR manager is starting up"
  progress (shown at every launch) is hidden; other background progress
  (library scans, add-on installs) still shows.

## 2.0.2.5 (2026-11-14)

- `1080i/IncludesDefaultSkinSettings.xml`: no Trakt Manager button on the info
  screen (this setup does not use Trakt) and no "BINGIE" logo in the corner of
  Home and the hubs (it covered the last row's tiles); both switched off once
  on devices that had them, and switching them back on in the skin settings
  sticks.

## 2.0.2.4 (2026-11-14)

- The name is Bengie (as in binge-watching) everywhere people see it: "Bengie
  2.0", "Bengie Repository", descriptions and messages. The add-on ids stay
  `skin.benjie` and `repository.benjie`, so nothing moves on devices.

## 2.0.2.3 (2026-11-14)

- `1080i/IncludesDefaultSkinSettings.xml`: no startup intro by default, and
  switched off once on devices that had it (choosing an intro again in the
  skin settings sticks). The 10-second intro video hid Home, so no artwork
  loaded until it ended, and it made every Home row load twice. Measured on
  one CPU core from a cold cache: first pictures on Home at 5 s instead of
  16 s, Home complete at 11 s instead of 21 s, 9 row loads instead of 18.
- `1080i/Font.xml`, `fonts/`: the default font is Inter, which has Arabic
  letters (Bingie's default, Netflix Sans, had none, so Arabic titles, cast
  and plots showed as boxes). The Netflix Sans files, Netflix's own font,
  are removed.

## 2.0.2.2 (2026-11-14)

- `addon.xml`: requires the Bengie builds of XStream Player (2.1.5.1),
  TMDb Bingie Helper (1.0.3.1) and Bingie Widgets (1.0.1.1) and IPTV Helper
  Fixes (1.9.0), so installing the skin from the Bengie repository installs
  everything. Studio logos and AutoCompletion are asked for at the versions
  Kodi's own repository has (0.0.24 and 2.1.2).
- `shortcuts/*.DATA.xml`: the Bengie build's home menu and rows are the
  defaults (Search, Home, New & Popular, Shows, Movies, Live TV, Categories,
  My List and their sub-menus).
- `1080i/Includes.xml`, `1080i/IncludesVariables.xml`: no first-run screens
  (Bingie's library-settings and add-video-sources prompts); Home opens
  straight away.
- `1080i/IncludesDefaultSkinSettings.xml`: the build's one non-default skin
  setting (`view510_detailsshowinfo`) is a default.

## 2.0.2.1

Bengie 2.0 is skin.bingie 2.0.2 by matke, modified by ahmadashwah on
2026-11-14 (GPL v2, section 2a). These are the changes; everything else is
Bingie as released.

Identity
- `addon.xml`: id `skin.benjie`, name "Bengie 2.0", version 2.0.2.1, credit
  to the Bingie authors in the provider name and description, source link.
- References to `skin.bingie` inside the skin (skinshortcuts' generated
  includes, the language file headers) now say `skin.benjie`.

Built in from IPTV Helper Fixes (these used to be patched into Bingie at
runtime by `service.iptvhelperfixes` 1.7.28 and earlier)
- `1080i/IncludesPaths.xml`: Home's first row is XStream Player's Continue
  Watching, the 2nd/3rd rows are New Arabic Movies / New Arabic TV Shows, the
  Movie/TV Show hub rows use XStream Player's continue-watching data, My List
  uses XStream Player's favourites, the Netflix Top 10 rows, and 12 streaming
  service rows (HBO / Max, Showtime, Hulu, Apple TV+, Peacock, Prime Video).
- `shortcuts/newhub.DATA.xml`: those streaming rows on New & Popular.
- `1080i/IncludesViewsLayoutPoster.xml`, `1080i/IncludesHomeWidgets.xml`:
  continue-watching progress bar, no empty title panel, Top 10 rank badge.
- `1080i/IncludesBingie.xml`: focus frame shows on unlabelled tiles,
  Continue Watching tiles play directly, the side menu header shows the IPTV
  profile name and opens XStream Player's settings, Live TV / Movies menu
  icons (antenna, clapperboard).
- `1080i/IncludesDialogVideoInfo.xml`: Play/Resume use XStream Player's next
  episode, a "Go to Season" button, the loading screen from every Play action.
- `1080i/Custom_1160_PlaybackLoading.xml` (new): black screen with a spinner
  while a stream is being found.
- `1080i/IncludesBingieSearch.xml`, `Includes.xml`,
  `Custom_1109_BingieSearch.xml`, `script-skinshortcuts-includes.xml`: Arabic
  search goes to XStream Player's catalog; the Search page always uses Kodi's
  full typing keyboard and opens it on a fresh search.
- `1080i/DialogAddonSettings.xml`: Down from the last setting reaches OK.
- `shortcuts/powermenu.DATA.xml`: no Reboot / Power off, an Update entry
  (XStream Player's update_patch).

New defaults
- `shortcuts/mainmenu.DATA.xml`: a Live TV entry (Kodi's channel list,
  `shortcuts/antenna.png`) after Movies.
- `1080i/IncludesDefaultSkinSettings.xml`: auto-pause when the OSD opens is
  off by default and the full search keyboard is on.
