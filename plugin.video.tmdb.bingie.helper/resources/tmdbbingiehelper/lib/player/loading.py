# Bengie: the skin's loading screen (Custom_1160_PlaybackLoading.xml) from the
# moment Play is pressed, not only once XStream Player starts the stream; the
# steps after this one (XStream Player's search, show, season and stream)
# raise the percentage. Issue #6.
from xbmcgui import Window

_PROPS = ('PlaybackLoading', 'PlaybackLoadingPercent', 'PlaybackLoadingStep')


def loading_start():
    try:
        win = Window(10000)
        win.setProperty('PlaybackLoadingPercent', '5')
        win.setProperty('PlaybackLoadingStep', '')
        win.setProperty('PlaybackLoading', '1')
    except Exception:
        pass


def loading_clear():
    try:
        win = Window(10000)
        for k in _PROPS:
            win.clearProperty(k)
    except Exception:
        pass
