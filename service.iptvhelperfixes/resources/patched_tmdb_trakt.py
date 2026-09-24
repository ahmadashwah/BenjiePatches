from tmdbbingiehelper.lib.files.ftools import cached_property


# XStream Player integration (BenjiePatches): this setup never scrobbles
# playback to Trakt, so the get_episode_playcount/get_episode_playprogress
# calls below always came back empty and every episode showed as unwatched.
# Checked first, before falling through to Trakt, using XStream Player's own
# real watch history via a cross-addon Files.GetDirectory call -- cached per
# show for the life of one episode-listing render, so it's one call per show
# per view, not one per episode. Safe no-op (falls straight through to the
# original Trakt behavior) if XStream Player isn't installed or has no data
# for that show.
_XSTREAM_WATCH_CACHE = {}


def _xstream_show_watch_data(showname):
    import xbmc
    key = (showname or '').strip().lower()
    if not key:
        xbmc.log("[IPTV Helper Fixes] _xstream_show_watch_data: empty showname, skipping", xbmc.LOGINFO)
        return {}
    if key in _XSTREAM_WATCH_CACHE:
        return _XSTREAM_WATCH_CACHE[key]
    data = {}
    try:
        import json
        import urllib.parse
        search_url = (
            "plugin://plugin.video.xstream-player/?mode=discover_watch_export"
            f"&showname={urllib.parse.quote(showname)}&profile_num=1"
        )
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "Files.GetDirectory",
            "params": {"directory": search_url, "media": "video", "properties": ["label"]},
        }
        result = json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
        xbmc.log(f"[IPTV Helper Fixes] _xstream_show_watch_data: showname={showname!r} rpc_result={result}", xbmc.LOGINFO)
        files = result.get("result", {}).get("files", []) or []
        if files:
            data = json.loads(files[0].get("label", "{}")) or {}
    except Exception as e:
        xbmc.log(f"[IPTV Helper Fixes] _xstream_show_watch_data error: {e}", xbmc.LOGINFO)
        data = {}
    _XSTREAM_WATCH_CACHE[key] = data
    return data


class TraktPlayData():
    def __init__(self, pauseplayprogress=False, watchedindicators=False, unwatchedepisodes=False, traktepisodetypes=True):
        self._pauseplayprogress = pauseplayprogress  # Set play progress using paused at position
        self._watchedindicators = watchedindicators  # Set watched status and playcount
        self._unwatchedepisodes = unwatchedepisodes  # Set unwatched episode count to total episode count for unwatched tvshows (if false)
        self._traktepisodetypes = traktepisodetypes  # Set episode_type property for episodes

    def is_sync(func):
        def wrapper(self, *args, **kwargs):
            if not self.trakt_syncdata:
                return
            return func(self, *args, **kwargs)
        return wrapper

    @cached_property
    def trakt_api(self):
        from tmdbbingiehelper.lib.api.trakt.api import TraktAPI
        api = TraktAPI()
        api.attempted_login = True  # Avoid asking for authorization
        return api

    @cached_property
    def trakt_syncdata(self):
        return self.trakt_api.trakt_syncdata

    @cached_property
    def trakt_episodedata(self):
        return self.trakt_api.trakt_episodedata

    @is_sync
    def pre_sync(self, info=None, tmdb_id=None, tmdb_type=None, season=None, **kwargs):
        info_movies = ('stars_in_movies', 'crew_in_movies', 'trakt_userlist', 'stars_in_both', 'crew_in_both',)
        if tmdb_type in ('movie', 'both',) or info in info_movies:
            if self._watchedindicators:
                self.trakt_syncdata.sync('movie', ('plays', ))
            if self._pauseplayprogress:
                self.trakt_syncdata.sync('movie', ('playback_progress', ))

        info_tvshow = ('stars_in_tvshows', 'crew_in_tvshows', 'trakt_userlist', 'trakt_calendar', 'stars_in_both', 'crew_in_both',)
        if tmdb_type in ('tv', 'season', 'both',) or info in info_tvshow:
            if self._watchedindicators:
                self.trakt_syncdata.sync('show', ('plays', 'watched_episodes', 'aired_episodes', ))
            if self._pauseplayprogress and tmdb_id is not None and season is not None:
                self.trakt_syncdata.sync('show', ('playback_progress', ))

    @is_sync
    def pre_sync_start(self, **kwargs):
        from tmdbbingiehelper.lib.addon.thread import SafeThread
        self._pre_sync = SafeThread(target=self.pre_sync, kwargs=kwargs)
        self._pre_sync.start()

    @is_sync
    def pre_sync_join(self):
        try:
            self._pre_sync.join()
        except AttributeError:
            return

    @is_sync
    def set_episode_type(self, li):
        if not self._traktepisodetypes:
            return
        if li.infolabels.get('mediatype') != 'episode':
            return
        tmdb = li.tmdb_id
        snum = li.season
        enum = li.episode
        if not tmdb or not snum or not enum:
            return
        episode_type = self.trakt_episodedata.get_value(tmdb, snum, enum, key='episode_type')
        if not episode_type:
            return
        li.infoproperties['episode_type'] = episode_type

    @is_sync
    def set_playprogress(self, li):

        def _set_playprogress():
            if li.infolabels.get('mediatype') == 'movie':
                return self.trakt_syncdata.get_movie_playprogress(
                    tmdb_id=li.unique_ids.get('tmdb'))

            if li.infolabels.get('mediatype') == 'episode':
                xstream_data = _xstream_show_watch_data(li.infolabels.get('tvshowtitle'))
                entry = xstream_data.get(str(li.infolabels.get('season') or ''), {}).get(
                    str(li.infolabels.get('episode') or ''))
                if entry and 'percent' in entry:
                    return entry['percent']

            return self.trakt_syncdata.get_episode_playprogress(
                tmdb_id=li.unique_ids.get('tvshow.tmdb'),
                season=li.infolabels.get('season'),
                episode=li.infolabels.get('episode'))

        if not self._pauseplayprogress:
            return

        if li.infolabels.get('mediatype') not in ['movie', 'episode']:
            return

        duration = li.infolabels.get('duration')
        if not duration:
            return

        progress = _set_playprogress()
        if not progress or progress < 4 or progress > 96:
            progress = 0

        li.infoproperties['ResumeTime'] = int(duration * progress // 100)
        li.infoproperties['TotalTime'] = int(duration)

    @is_sync
    def get_playcount(self, li):
        import xbmc
        xbmc.log(
            f"[IPTV Helper Fixes] get_playcount called: mediatype={li.infolabels.get('mediatype')!r} "
            f"tvshowtitle={li.infolabels.get('tvshowtitle')!r} season={li.infolabels.get('season')!r} "
            f"episode={li.infolabels.get('episode')!r} watchedindicators={self._watchedindicators!r}",
            xbmc.LOGINFO,
        )
        if not self._watchedindicators:
            return

        if li.infolabels.get('mediatype') == 'movie':
            return self.trakt_syncdata.get_movie_playcount(
                tmdb_id=li.unique_ids.get('tmdb')) or 0

        if li.infolabels.get('mediatype') == 'episode':
            xstream_data = _xstream_show_watch_data(li.infolabels.get('tvshowtitle'))
            entry = xstream_data.get(str(li.infolabels.get('season') or ''), {}).get(
                str(li.infolabels.get('episode') or ''))
            if entry and entry.get('playcount'):
                return 1
            return self.trakt_syncdata.get_episode_playcount(
                tmdb_id=li.unique_ids.get('tvshow.tmdb'),
                season=li.infolabels.get('season'),
                episode=li.infolabels.get('episode')) or 0

        if li.infolabels.get('mediatype') == 'tvshow':
            air_count = self.trakt_syncdata.get_episode_airedcount(
                tmdb_id=li.unique_ids.get('tvshow.tmdb') or li.unique_ids.get('tmdb'))
            if air_count and air_count > 0:
                li.infolabels['episode'] = air_count
            air_count = max(int(li.infolabels.get('episode') or 0), int(air_count or 0), 0)
            return min(self.trakt_syncdata.get_episode_watchedcount(
                tmdb_id=li.unique_ids.get('tvshow.tmdb') or li.unique_ids.get('tmdb')) or 0, air_count)

        if li.infolabels.get('mediatype') == 'season':
            air_count = self.trakt_syncdata.get_episode_airedcount(
                tmdb_id=li.unique_ids.get('tvshow.tmdb'),
                season=li.infolabels.get('season'))
            if air_count and air_count > 0:
                li.infolabels['episode'] = air_count
            air_count = max(int(li.infolabels.get('episode') or 0), int(air_count or 0), 0)
            return min(self.trakt_syncdata.get_episode_watchedcount(
                tmdb_id=li.unique_ids.get('tvshow.tmdb'),
                season=li.infolabels.get('season')) or 0, air_count)
