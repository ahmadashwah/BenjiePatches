# -*- coding: utf-8 -*-
"""Script entry, run by file path: RunScript(special://home/addons/service.iptvhelperfixes/connect.py,connect|disconnect|update).

connect / disconnect are the settings buttons for the GitHub sign-in; update
is the power menu's Update (via XStream Player's update_patch mode)."""
import sys

action = sys.argv[1] if len(sys.argv) > 1 else "connect"
if action == "update":
    import benjie_update

    benjie_update.run_interactive()
else:
    import github_login

    if action == "disconnect":
        github_login.disconnect()
    else:
        github_login.connect()
