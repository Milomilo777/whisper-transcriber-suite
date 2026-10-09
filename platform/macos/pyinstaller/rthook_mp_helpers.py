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

_WTS_HELPER_MODULES = (
    "multiprocessing.resource_tracker",
    "multiprocessing.forkserver",
)


def _wts_helper_code(command):
    """Compiled code of an exact multiprocessing helper command, else None.

    The command is what multiprocessing builds: ``from <module> import main``
    followed by one ``main(<literals>)`` call (the forkserver one may end in
    ``**{<literals>}``). Anything else, such as more code after the prefix,
    is refused, so a ``-c`` argument cannot make the app run arbitrary code.
    """
    import ast

    try:
        body = ast.parse(command).body
        if len(body) != 2:
            return None
        imp, stmt = body
        if not (
            isinstance(imp, ast.ImportFrom)
            and imp.level == 0
            and imp.module in _WTS_HELPER_MODULES
            and [(a.name, a.asname) for a in imp.names] == [("main", None)]
        ):
            return None
        call = stmt.value if isinstance(stmt, ast.Expr) else None
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "main"
        ):
            return None
        for arg in call.args:
            ast.literal_eval(arg)
        for kw in call.keywords:
            value = ast.literal_eval(kw.value)
            if kw.arg is None and not isinstance(value, dict):
                return None
        return compile(ast.Module(body=body, type_ignores=[]), "<multiprocessing helper>", "exec")
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def _wts_divert_multiprocessing_helper() -> None:
    argv = sys.argv
    try:
        idx = argv.index("-c")
    except ValueError:
        return
    if idx + 1 >= len(argv):
        return
    code = _wts_helper_code(argv[idx + 1])
    if code is not None:
        exec(code)
        sys.exit()


_wts_divert_multiprocessing_helper()
del _wts_divert_multiprocessing_helper
