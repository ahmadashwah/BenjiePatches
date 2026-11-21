# Changes from Bingie 2.0.2

## 2.0.2.14 (2026-11-21)

- Kodi 22 support (`1080i/Home.xml`, `1080i/SkinSettings.xml`): Kodi 22 comes
  with Skin Shortcuts 3, which can't read this skin's menu files and stopped
  with a "built for Skin Shortcuts v2" message. With Skin Shortcuts 3 the skin
  no longer asks it to rebuild the menus and uses the shipped
  `1080i/script-skinshortcuts-includes.xml` as it is; menus can't be edited
  on Kodi 22 for now. Kodi 21 is unchanged.
- `1080i/script-skinshortcuts-includes.xml` rebuilt from the current menu
  files (the Home / New & Popular rows from 2.0.2.11), so Kodi 22 devices get
  the same rows as Kodi 21.
- Tested on Kodi 22.0 RC2: Home and its rows, playback from Continue Watching
  and through TMDb Bingie Helper, results while typing and Back on the search
  keyboard.

## 2.0.2.13 (2026-11-15)

- `1080i/IncludesBingieKeyboard.xml`: the live result rows beside the search
  keyboard now show as soon as there is text of their kind. They were hidden
  until they had items, and Kodi only loads a row while it is visible, so in
  2.0.2.12 no search ever started.

## 2.0.2.12 (2026-11-15)

- Search keyboard (`1080i/IncludesBingieKeyboard.xml`, `IncludesBingieSearch.xml`,
  `Includes.xml`):
  - Results appear beside the keyboard while typing: TMDb for Latin text,
    XStream Player's shows and movies for Arabic (`IsArabicLiveTerm`); each
    letter refreshes them. Right from the keys moves into them, and a result
    opens its information page.
  - Back keeps what was typed (it presses Done) instead of discarding it, so
    the check mark is optional.

## 2.0.2.11 (2026-11-15)

- Rows moved between Home and New & Popular (`1080i/IncludesPaths.xml`,
  `shortcuts/10000-1.DATA.xml`, `shortcuts/newhub.DATA.xml`):
  - Home: Continue Watching, New Arabic Movies, New Arabic TV Shows, Last
    Releases Movies, Last Releases TV Shows, Movies Trending Today, TV Shows
    Trending Today, IMDB Top 250 TV Shows.
  - New & Popular: Netflix Top 10 - TV Shows, Netflix Top 10 - Movies, then
    the streaming-service rows.
  Devices pick this up when Skin Shortcuts rebuilds the menus after the
  update; a device whose Home or New & Popular rows were customized keeps
  its own rows.

## 2.0.2.10 (2026-11-15)

- Touch mode, a new switch in the skin settings (General, Advanced): shows an
  on-screen "‹ Back" button at the top right of the info page, the Search page
  and video lists, so a touchscreen without keys can leave them (issue #19).
  Off by default; remotes see no change. (`1080i/Includes.xml`
  `Bengie_TouchBackButton`, `1080i/IncludesSkinSettings.xml`,
  `1080i/DialogVideoInfo.xml`, `1080i/MyVideoNav.xml`, strings 31590-31592.)
- `1080i/Custom_1109_BingieSearch.xml`: tapping (or clicking) the search text
  or the "full keyboard" hint opens the full keyboard; with Touch mode on the
  hint says "Tap here for full keyboard" instead of "Press up…" (issue #16).
  Pressing Up still works.

## 2.0.2.9 (2026-11-15)

- `1080i/Custom_1161_SearchTermChanged.xml` (new): the Search page searches
  whatever was typed, however it was typed. The first search, typed in the
  keyboard the page opens by itself, used to show "There are no matches for
  your search" because nothing ever asked for its results (issue #15).
- `1080i/Custom_1109_BingieSearch.xml`, `1080i/IncludesBingieSearch.xml`:
  Arabic search works.
  - The XStream Player results were only in the shipped copy of the menu file
    that Skin Shortcuts regenerates, so they were lost on devices after any
    menu rebuild. They're now a normal skin include.
  - Both result sets are always on the page: XStream Player for Arabic terms,
    TMDb for the rest. Before, the choice was made when the page opened, so an
    Arabic term typed on the page was searched on TMDb and found nothing
    (issue #14).
- Comes with:
  - IPTV Helper Fixes 1.9.7: adds Kodi's Arabic keyboard layout once, next to
    English; the keyboard's layout button switches between them (issue #14).
  - XStream Player 2.1.5.5: the skin's search rows no longer write XStream's
    search history (the movie and series searches ran at the same moment and
    one failed on Windows with "file in use"), and an empty row shows nothing
    instead of a blank "No results" tile.

## 2.0.2.8 (2026-11-14)

- `1080i/Custom_1160_PlaybackLoading.xml`: the loading screen shows how far
  along it is: a percentage inside the spinner and the current step below it
  (finding the title, loading the show, loading the episodes, starting the
  stream). The steps are real, not a timer. TMDb Bingie Helper 1.0.3.4 now
  shows the screen right at the click; it used to show up about 6.5 s
  after it (issue #6).
- Comes with:
  - XStream Player 2.1.5.4: plays the preferred language copy of a show or
    movie (AR-SUBS, then EN, then other AR) without a picker (issue #4). It
    also keeps a show's details for 10 minutes, so it no longer downloads
    them three times per episode; from click to picture is now about 7 s
    instead of 9 s.
  - IPTV Helper Fixes 1.9.5: brings back the Kodi settings from Bingie's
    first-run screen once per device: no ".." entries, focus on the next
    unwatched episode, Select resumes (issue #5).
  - TMDb Bingie Helper 1.0.3.4: a show with one aired season opens its
    episodes directly.

## 2.0.2.7 (2026-11-14)

- `1080i/IncludesBingie.xml`: clicking a Continue Watching tile plays it and
  resumes where it stopped. It only set the loading flag before, so the
  loading screen showed and nothing played (issue #1).
- `1080i/Custom_1160_PlaybackLoading.xml`: the loading screen steps aside
  while a dialog that needs an answer is open (resume menu, picker, yes/no,
  OK, keyboard, progress) and comes back afterwards; it used to cover them, so
  the "Resume from" menu was hidden and the spinner seemed stuck (issue #2).

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
