"""Drive an X11 desktop with real input events and take a screenshot after each step.

Used by .github/workflows/linux-gui-click.yml to click through the app on a virtual Linux
display (Xvfb + a window manager). Input goes through xdotool (XTEST), so Tk sees the same
events a person's mouse and keyboard produce; screenshots come from ImageMagick ``import``.

usage: python tools/linux_gui/x11_hands.py ACTIONS.json OUT_DIR

ACTIONS.json is a JSON list of steps, the same shape as the Windows gui-hands daemon:
  {"op": "launch", "cmd": [...], "env": {...}, "cwd": "..."}   start a program (kept running)
  {"op": "wait", "s": 2}                                         sleep (at most 120 s per step)
  {"op": "shot", "name": "01-start"}                             full-screen PNG into OUT_DIR
  {"op": "click", "x": 10, "y": 20, "button": 1, "double": false}
  {"op": "move", "x": 10, "y": 20}
  {"op": "scroll", "x": 10, "y": 20, "dir": "down", "clicks": 3}
  {"op": "type", "text": "hello"}                                Unicode text via xdotool type
  {"op": "key", "keys": ["ctrl", "a"]}                           one chord, pressed together
  {"op": "windows"}                                              titles + geometry of visible windows
  {"op": "focus", "title": "Whisper"}                            activate the first window whose title matches
Every string may hold ``{{NAME}}``, replaced by the environment variable ``HANDS_NAME`` (the
workflow sets HANDS_REPO, HANDS_PROFILE, HANDS_MEDIA); an unknown name is an error.
Results go to OUT_DIR/results.json; the script exits 1 when a step failed, after running the rest.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MAX_WAIT_S = 120.0
OPS = {"launch", "wait", "shot", "click", "move", "scroll", "type", "key", "windows", "focus"}
# xdotool key names for the friendly names the Windows daemon accepts.
KEY_NAMES = {
    "ctrl": "ctrl", "alt": "alt", "shift": "shift", "win": "super", "enter": "Return",
    "tab": "Tab", "esc": "Escape", "escape": "Escape", "backspace": "BackSpace",
    "delete": "Delete", "space": "space", "up": "Up", "down": "Down", "left": "Left",
    "right": "Right", "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
    **{f"f{n}": f"F{n}" for n in range(1, 13)},
}


_PLACEHOLDER = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def expand(value: Any, environ: Any = None) -> Any:
    """``value`` with every ``{{NAME}}`` in its strings replaced by ``HANDS_NAME`` from the environment."""
    env = os.environ if environ is None else environ
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            key = "HANDS_" + m.group(1)
            if key not in env:
                raise KeyError(f"placeholder {m.group(0)} needs the environment variable {key}")
            return env[key]
        return _PLACEHOLDER.sub(sub, value)
    if isinstance(value, list):
        return [expand(v, env) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, env) for k, v in value.items()}
    return value


def validate(actions: Any) -> list[str]:
    """Problems with an action list, as readable lines; empty when it can run."""
    if not isinstance(actions, list):
        return ["the actions must be a JSON list"]
    problems = []
    for i, a in enumerate(actions):
        if not isinstance(a, dict) or a.get("op") not in OPS:
            problems.append(f"step {i}: unknown or missing op")
            continue
        op = a["op"]
        if op in ("click", "move", "scroll") and not all(isinstance(a.get(k), int) for k in ("x", "y")):
            problems.append(f"step {i}: {op} needs integer x and y")
        # run_step() scrolls up for every dir but the exact "down", so catch typos here.
        if op == "scroll" and a.get("dir", "down") not in ("up", "down"):
            problems.append(f"step {i}: scroll dir must be up or down")
        if op == "key" and not (isinstance(a.get("keys"), list) and a["keys"]
                                and all(isinstance(k, str) and k for k in a["keys"])):
            # A string here was typed character by character by the Windows daemon (2026-10-26).
            problems.append(f"step {i}: key needs a non-empty list of key names, e.g. [\"ctrl\", \"a\"]")
        if op == "type" and not isinstance(a.get("text"), str):
            problems.append(f"step {i}: type needs text")
        if op == "launch" and not (isinstance(a.get("cmd"), list) and a["cmd"]):
            problems.append(f"step {i}: launch needs a non-empty cmd list")
        if op == "wait" and not (isinstance(a.get("s"), (int, float)) and 0 <= a["s"] <= MAX_WAIT_S):
            problems.append(f"step {i}: wait needs 0 <= s <= {MAX_WAIT_S:g}")
        if op == "focus" and not isinstance(a.get("title"), str):
            problems.append(f"step {i}: focus needs a title")
    return problems


def chord(keys: list[str]) -> str:
    """xdotool's chord syntax for a list of friendly key names: ["ctrl", "a"] -> "ctrl+a"."""
    return "+".join(KEY_NAMES.get(k.lower(), k) for k in keys)


def _xdo(*args: str) -> str:
    return subprocess.run(["xdotool", *args], check=True, capture_output=True, text=True).stdout


def _windows() -> list[dict[str, Any]]:
    out = []
    ids = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "."],
                         capture_output=True, text=True).stdout.split()
    for wid in ids:
        try:
            name = _xdo("getwindowname", wid).strip()
            geo = dict(line.split("=", 1) for line in _xdo("getwindowgeometry", "--shell", wid).split())
        except subprocess.CalledProcessError:
            continue
        out.append({"id": wid, "title": name, "x": int(geo["X"]), "y": int(geo["Y"]),
                    "w": int(geo["WIDTH"]), "h": int(geo["HEIGHT"])})
    return out


def run_step(a: dict[str, Any], out_dir: Path, n: int, procs: list[subprocess.Popen]) -> dict[str, Any]:
    op = a["op"]
    if op == "launch":
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (a.get("env") or {}).items()})
        log = open(out_dir / f"launch-{n:02d}.log", "wb")  # noqa: SIM115 - kept open for the child
        p = subprocess.Popen(a["cmd"], cwd=a.get("cwd"), env=env, stdout=log, stderr=subprocess.STDOUT)
        procs.append(p)
        return {"pid": p.pid}
    if op == "wait":
        time.sleep(float(a["s"]))
        return {}
    if op == "shot":
        name = f"{n:02d}-{a.get('name') or 'shot'}.png"
        subprocess.run(["import", "-window", "root", str(out_dir / name)], check=True)
        return {"file": name}
    if op in ("click", "move", "scroll"):
        _xdo("mousemove", str(a["x"]), str(a["y"]))
        if op == "click":
            reps = ["--repeat", "2", "--delay", "80"] if a.get("double") else []
            _xdo("click", *reps, str(a.get("button", 1)))
        elif op == "scroll":
            button = "5" if a.get("dir", "down") == "down" else "4"
            _xdo("click", "--repeat", str(int(a.get("clicks", 3))), "--delay", "40", button)
        return {}
    if op == "type":
        _xdo("type", "--delay", "40", "--", a["text"])
        return {}
    if op == "key":
        _xdo("key", "--clearmodifiers", chord(a["keys"]))
        return {}
    if op == "windows":
        return {"windows": _windows()}
    if op == "focus":
        for w in _windows():
            if a["title"].lower() in w["title"].lower():
                _xdo("windowactivate", "--sync", w["id"])
                return {"focused": w["title"]}
        raise RuntimeError(f"no visible window titled like {a['title']!r}")
    raise RuntimeError(f"unknown op {op}")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    actions = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    problems = validate(actions)
    if not problems:
        try:
            actions = expand(actions)
        except KeyError as e:
            problems = [str(e.args[0])]
    if problems:
        print("\n".join(problems))
        return 2
    out_dir = Path(argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    procs: list[subprocess.Popen] = []
    results, failed = [], False
    for n, a in enumerate(actions):
        try:
            r = {"step": n, "op": a["op"], "ok": True, **run_step(a, out_dir, n, procs)}
        except Exception as e:  # noqa: BLE001 - every step's failure is recorded, then the run goes on
            r = {"step": n, "op": a["op"], "ok": False, "error": f"{type(e).__name__}: {e}"}
            failed = True
        results.append(r)
        print(json.dumps(r, ensure_ascii=False), flush=True)
    for p in procs:
        r = p.poll()
        results.append({"launched_pid": p.pid, "exit_code": r})
    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
