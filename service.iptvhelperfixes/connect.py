# -*- coding: utf-8 -*-
"""Script entry for the settings buttons: RunScript(service.iptvhelperfixes,connect|disconnect)."""
import sys

import github_login

if len(sys.argv) > 1 and sys.argv[1] == "disconnect":
    github_login.disconnect()
else:
    github_login.connect()
