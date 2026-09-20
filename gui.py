"""Entry point. Five modes:

  python gui.py                     → launch the Tk app (default)
  python gui.py --worker            → spawn the JSON-stdio transcription worker
  python gui.py --voice-clone-worker → spawn the Clone Your Voice worker
  python gui.py transcribe FILE     → CLI transcription
  python gui.py serve               → run the local-network HTTP job server
  python gui.py --help              → usage

The worker modes are invoked by the App spawning its own exe; do
NOT remove or rename the ``--worker`` / ``--voice-clone-worker`` shapes
— they're the spawn-contract every method of the deliverables uses.
The two are separate, independent worker scripts (see
``core.voice_clone_worker``'s docstring for why voice cloning isn't a
new action on the transcription worker's protocol).
"""
import argparse
import sys


def _ensure_safe_stdio_encoding() -> None:
    """Make stdout/stderr survive a character the console codepage cannot
    encode, instead of raising UnicodeEncodeError out of a print() call.

    Windows' legacy console codepage (cp1252 or similar) cannot encode most
    emoji; a downloaded media file with one in its title (e.g. a name yt-dlp
    pulled from a social-media post) reaches ``print()`` via the transcribe
    progress/log callbacks and crashed every single log line for the rest
    of the run. Not called for ``--worker`` mode, whose stdout is a
    structured JSON-lines protocol the parent process depends on verbatim.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except Exception:  # noqa: BLE001
                pass


def _cli_transcribe(args: argparse.Namespace) -> int:
    """Run a one-shot transcription from the command line."""
    import os
    import time
    from core.config import load_config, save_config
    from core.task import TranscriptionTask
    from core import transcriber as _trans

    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        print(f"error: file not found: {src}", file=sys.stderr)
        return 2

    cfg = load_config()
    formats = args.formats or cfg.get("output_formats") or ["srt", "json"]
    cfg["output_formats"] = formats
    # Mirror the explicit CLI flags onto cfg so save_config writes
    # them through AND the module-level _trans.config snapshot is
    # refreshed to match — the worker module was originally read
    # once at import time and never re-read non-diarization keys
    # like output_formats, so the FIRST CLI run with new --formats
    # / --diarization silently fell back to whatever was on disk
    # at import time.
    if args.diarization:
        cfg["diarization_enabled"] = True
    save_config(cfg)
    # CRITICAL — _trans.config was loaded at import time. Refresh it
    # so the writer sees the just-saved values on this very run.
    _trans.config.update(cfg)

    print("[cli] loading model...", flush=True)
    if not _trans.load_existing_model(lambda m: print(f"[cli] {m}", flush=True)):
        print("error: model not loaded", file=sys.stderr)
        return 3

    task = TranscriptionTask(src)
    if args.language:
        task.language = args.language

    # History entry — match the GUI path so CLI usage doesn't
    # silently bypass the recent-files / statistics surfaces.
    history_db = None
    history_id = None
    try:
        from core.history import HistoryDB
        history_db = HistoryDB()
        history_id = history_db.insert_transcription(
            src,
            model=(cfg.get("model") or {}).get("name", ""),
            language=args.language or "",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[cli] history.db unavailable: {e}", flush=True)
        history_db = None

    def _on_log(m: str) -> None:
        print(f"[cli] {m}", flush=True)

    last_progress = {"value": -1}

    def _on_progress(p: int) -> None:
        # Emit a single line per percentage so CLI users can see the
        # same live progress the GUI gets from the worker events.
        if p != last_progress["value"]:
            last_progress["value"] = p
            print(f"[cli] progress {p}%", flush=True)

    started = time.time()
    status = "finished"
    error_msg = ""
    try:
        _trans.transcribe(task, _on_progress, _on_log, language_cb=None)
    except Exception as e:  # noqa: BLE001
        status = "error"
        error_msg = str(e)
        print(f"[cli] ERROR: {e}", file=sys.stderr, flush=True)
    duration_s = time.time() - started

    written = [
        p for p in list(getattr(task, "output_paths", None) or [])
        if os.path.isfile(p)
    ]
    if not written:
        base, _ = os.path.splitext(src)
        written = []
        for ext in formats:
            candidate = f"{base}.{ext}"
            if os.path.isfile(candidate):
                written.append(candidate)
    if status == "finished":
        print(f"[cli] wrote {len(written)} output(s) next to {src}", flush=True)
        for p in written:
            print(f"  {p}", flush=True)

    if history_db is not None and history_id is not None:
        try:
            history_db.finish_transcription(
                history_id, status,
                output_paths=written,
                duration_seconds=duration_s,
                language=getattr(task, "detected_language", "") or args.language or "",
                error=error_msg,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[cli] could not finish history row: {e}", flush=True)
        try:
            history_db.close()
        except Exception:  # noqa: BLE001
            pass

    return 0 if status == "finished" else 4


def _cli_serve(args: argparse.Namespace) -> int:
    """Run the optional local-network / web HTTP job server.

    Default bind is loopback (127.0.0.1) so it never triggers a Windows
    firewall prompt. ``--lan`` (or an explicit ``--host 0.0.0.0``) binds all
    interfaces for the LAN case — that is the ONLY path that pops the
    Windows Defender prompt, which is why it must be an explicit opt-in.
    """
    from core.config import load_config
    from core.server import run_server

    cfg = load_config()
    host = args.host
    if args.lan:
        host = "0.0.0.0"
    port = args.port if args.port is not None else int(cfg.get("server_port", 8765))
    max_upload_mb = (
        args.max_upload_mb if args.max_upload_mb is not None
        else int(cfg.get("server_max_upload_mb", 512))
    )
    https = bool(args.https) or bool(cfg.get("server_https_enabled", False))
    webhook_url = (
        args.webhook if args.webhook is not None
        else str(cfg.get("server_webhook_url", ""))
    )
    return run_server(
        host=host, port=port, token=args.token or "",
        max_upload_mb=max_upload_mb,
        https=https, webhook_url=webhook_url,
    )


def _build_argparser() -> argparse.ArgumentParser:
    from core.writers import supported_formats

    p = argparse.ArgumentParser(
        prog="WhisperTranscriberSuite",
        description=(
            "Offline transcription + downloader. Run without arguments to "
            "launch the desktop app. Add --safe-mode to launch with the "
            "user config backed up + reset to defaults (recovery)."
        ),
    )
    sub = p.add_subparsers(dest="command")

    tr = sub.add_parser("transcribe", help="Transcribe a file and exit (no UI)")
    tr.add_argument("file", help="audio/video file to transcribe")
    tr.add_argument(
        "--language", "-l", default="",
        help="force a language code (en, es, fa, …); empty = auto-detect",
    )
    tr.add_argument(
        "--formats", "-f", nargs="+",
        choices=tuple(supported_formats()),
        help="output formats (default: from config.json)",
    )
    tr.add_argument(
        "--diarization", action="store_true",
        help="enable speaker diarization for this transcription",
    )

    sv = sub.add_parser(
        "serve",
        help="Run the local-network / web HTTP job server (no UI)",
    )
    sv.add_argument(
        "--port", "-p", type=int, default=None,
        help="TCP port to listen on (default: config server_port or 8765)",
    )
    sv.add_argument(
        "--host", default="127.0.0.1",
        help="bind address (default 127.0.0.1 = loopback only, no firewall "
             "prompt). Use --lan or --host 0.0.0.0 to share on the network.",
    )
    sv.add_argument(
        "--lan", action="store_true",
        help="bind all interfaces (0.0.0.0) for LAN access - explicit opt-in "
             "because this is what triggers the Windows firewall prompt",
    )
    sv.add_argument(
        "--token", default="",
        help="optional shared secret; clients must send it via the "
             "X-Auth-Token header or ?token= query",
    )
    sv.add_argument(
        "--max-upload-mb", type=int, default=None, dest="max_upload_mb",
        help="reject uploads larger than this many MB "
             "(default: config server_max_upload_mb or 512)",
    )
    sv.add_argument(
        "--https", action="store_true",
        help="serve over TLS with a self-signed certificate generated once "
             "under the app's user-data folder (default: config "
             "server_https_enabled, off)",
    )
    sv.add_argument(
        "--webhook", default=None,
        help="POST a small JSON payload to this URL when a job finishes "
             "(success or failure); default: config server_webhook_url "
             "(empty = off). Loopback / link-local / cloud-metadata targets "
             "are refused",
    )
    return p


def _activate_safe_mode() -> None:
    """Move the user's config aside + force fresh defaults this run.

    Used by ``--safe-mode``. Renames
    ``%LOCALAPPDATA%\\WhisperTranscriberSuite\\config.json`` to
    ``config.json.safemode_backup-<timestamp>`` so the next launch
    of ``load_config()`` returns ``DEFAULT_CONFIG`` with empty
    ``hub_folder`` — the first-run dialog fires fresh. The user's
    real config is preserved (renamed, not deleted) so they can
    swap it back if they want.

    Idempotent: if the config file doesn't exist (clean profile),
    this is a no-op.
    """
    import os
    import time
    from core.config import config_path

    cfg_path = config_path()
    if not os.path.exists(cfg_path):
        print(f"[safe-mode] no config to back up at {cfg_path}", flush=True)
        return
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{cfg_path}.safemode_backup-{stamp}"
    try:
        os.replace(cfg_path, backup)
        print(f"[safe-mode] config backed up to {backup}", flush=True)
        print("[safe-mode] launching with default config + fresh "
              "first-run hub dialog.", flush=True)
    except OSError as e:
        print(f"[safe-mode] could not back up config: {e}", file=sys.stderr,
              flush=True)


def main() -> int:
    # Worker mode is a special early branch — bypasses argparse so
    # we never break the spawn-contract.
    if "--worker" in sys.argv:
        from core.worker import main as _worker_main
        return _worker_main()
    if "--voice-clone-worker" in sys.argv:
        from core.voice_clone_worker import main as _voice_clone_worker_main
        return _voice_clone_worker_main()

    _ensure_safe_stdio_encoding()

    # --safe-mode is also handled before argparse so the user can
    # combine it with the default GUI launch without juggling
    # subcommands. The flag is sticky for this run only — the next
    # launch picks up the (renamed) old config or the freshly-saved
    # one, whichever the user committed via the first-run dialog.
    if "--safe-mode" in sys.argv:
        _activate_safe_mode()
        # Remove the flag from argv so argparse below doesn't choke.
        sys.argv = [a for a in sys.argv if a != "--safe-mode"]

    parser = _build_argparser()
    args = parser.parse_args()

    if args.command == "transcribe":
        return _cli_transcribe(args)

    if args.command == "serve":
        return _cli_serve(args)

    # Default: launch the Tk app.
    from app import run
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
