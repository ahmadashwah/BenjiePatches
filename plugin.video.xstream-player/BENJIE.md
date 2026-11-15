# plugin.video.xstream-player 2.1.5.1 (Bengie build)

A modified version of plugin.video.xstream-player 2.1.5 by Pesicp (XStream Player), made for the Bengie skin by ahmadashwah (2026-11-14). All credit for the original add-on goes to its authors. License: MIT, the same as the original.

## Changes

- resources/lib/addon.py: the IPTV Helper Fixes patches (series search ids, provider prefix clean-up, EPG notification fixes, Continue Watching, Netflix Top 10 and streaming service rows, next-up, favourites export, autoplay, playback loading screen, the Update entry and more; see the service.iptvhelperfixes changelog for the full history).
- resources/lib/history.py: resume points keep posters, finished markers, partial-progress lookup.
- resources/lib/defusedxml/: bundled so the EPG parser accepts standard XMLTV feeds.
- The Update entry (update_patch) runs the Bengie updater in service.iptvhelperfixes.
- resources/lib/addon.py: display titles without year/region tags ("(2005) (US)"), coming-soon brackets or a trailing Arabic alternate title (the original name is still used for playback, history and favourites); Continue Watching items carry plot, year, genre, rating and backdrop from the cached catalog; TMDb posters at w342 for row tiles.
- resources/lib/epg.py: the XMLTV export for the Live TV guide is built with the standard library (defusedxml cannot build XML, so the guide was written empty).
