# PyInstaller runtime hook for the macOS .app (whisper_project_mac.spec).
#
# Adapted from PyInstaller (https://github.com/pyinstaller/pyinstaller) —
# the helper-process diversion in PyInstaller/hooks/rthooks/pyi_rth_multiprocessing.py.
#
# multiprocessing starts its resource-tracker / forkserver helpers as
#     <sys.executable> <interpreter flags> -c "from multiprocessing.resource_tracker import main;main(6)"
# In a frozen app sys.executable IS the app, so without a diversion the
# helper re-enters gui.py, argparse rejects the "-c" command and the tracker
# dies ("resource_tracker: process died unexpectedly, relaunching").
# PyInstaller only diverts this inside multiprocessing.freeze_support(), which
# gui.py does not call, and custom runtime hooks run BEFORE PyInstaller's own
# ones — so do the (argv-only, side-effect-free) diversion here.
import sys


def _wts_divert_multiprocessing_helper() -> None:
    argv = sys.argv
    try:
        idx = argv.index("-c")
    except ValueError:
        return
    if idx + 1 >= len(argv):
        return
    command = argv[idx + 1]
    if command.startswith((
        "from multiprocessing.resource_tracker import main",
        "from multiprocessing.forkserver import main",
    )):
        exec(command)
        sys.exit()


_wts_divert_multiprocessing_helper()
del _wts_divert_multiprocessing_helper
