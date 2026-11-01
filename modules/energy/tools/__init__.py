"""Diagnostic command-line tools. Run from the project folder as `py -m tools.<name>`.

They talk to the real hardware, so the web server must be stopped first (it holds the MasterBus USB Link exclusively and
owns the Bluetooth radio). Everything is read-only unless the tool says otherwise and asks for `--confirm-write`.
"""
