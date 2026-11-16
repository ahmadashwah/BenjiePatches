# -*- coding: utf-8 -*-
"""XStream Player's entry point (addon.xml points Kodi here).

Bengie: the add-on's code lives in xstream_app.py and runs when it is
imported. Python never keeps a compiled copy of the file a run starts from,
so with all 13,000 lines here Kodi compiled them again for every Home row,
menu and click; as an imported module it is compiled once and reused
(__pycache__). Every call still runs the code fresh, as before."""
import xstream_app  # noqa: F401
