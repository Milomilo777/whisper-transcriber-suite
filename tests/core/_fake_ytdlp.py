"""A stand-in for yt-dlp that writes into a real folder, for the download-ownership tests.

Not a test module (the leading underscore keeps pytest from collecting it). It reads the same
flags the app passes (``-o``, ``-x``, ``--audio-format``, ``-k``, ``--print``, ``--merge-output-
format``) and mimics the yt-dlp behaviours the tests depend on:

* the title is the last path part of the URL (percent-decoded); a URL whose path starts with
  ``/playlist/`` holds comma-separated titles, one item each;
* ``--print`` is the plan pass: one ``wts-plan:<planned filename>`` line per item, nothing written;
* a real run prints ``[download] Destination:`` and writes ``video:<url>``; a file that is already
  there is ``has already been downloaded`` (and, with ``-x`` and no ``-k``, still converted and then
  deleted, as yt-dlp does); a ``.part`` next to it is resumed and its old bytes are kept;
* ``-x`` writes ``<title>.<audio format>`` after ``[ExtractAudio] Destination:`` and removes the
  source unless ``-k`` was given;
* environment: ``FAKE_YTDLP_LOG`` (file that gets one line per run: plan or real),
  ``FAKE_YTDLP_PLAN_FAIL=1`` (the plan pass fails), ``FAKE_YTDLP_FAIL_CONVERT=<title>`` (writes a
  truncated target for that title, then dies with exit code 1, like a killed conversion),
  ``FAKE_YTDLP_DIE_PART=1`` (writes ``<file>.part`` and dies),
  ``FAKE_YTDLP_HANG_CONVERT=<title>`` (writes a truncated target, then waits to be killed),
  ``FAKE_YTDLP_SLOW=<seconds>`` (pause after announcing a file, so a test can stop the run first);
* ``--skip-download`` is the caption phase: ``<title>.<leading letters of --sub-langs>.vtt`` is written for
  each item and announced with ``Writing video subtitles to:``.
"""
from __future__ import annotations

import os
import re
import sys
import time
import urllib.parse


def main(argv: list[str]) -> int:
    template = ""
    audio = False
    audio_format = "mp3"
    keep = False
    plan = False
    merge = "mp4"
    captions = False
    sub_lang = "en"
    i = 0
    url = ""
    while i < len(argv):
        a = argv[i]
        if a == "--":
            url = argv[i + 1]
            break
        if a == "-o":
            template = argv[i + 1]
            i += 1
        elif a == "-x":
            audio = True
        elif a == "--audio-format":
            audio_format = argv[i + 1]
            i += 1
        elif a == "-k":
            keep = True
        elif a == "--print":
            plan = True
            i += 1
        elif a == "--merge-output-format":
            merge = argv[i + 1]
            i += 1
        elif a == "--skip-download":
            captions = True
        elif a == "--sub-langs":
            sub_lang = (re.match(r"[A-Za-z]+", argv[i + 1]) or re.match(r"(en)", "en")).group(0)
            i += 1
        elif a in ("-f", "--ffmpeg-location", "--encoding", "--progress-template",
                   "--sponsorblock-remove", "--download-sections"):
            i += 1
        i += 1
    log = os.environ.get("FAKE_YTDLP_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(("plan" if plan else "real") + " " + " ".join(argv) + "\n")
    path = urllib.parse.urlparse(url).path
    if path.startswith("/playlist/"):
        titles = [urllib.parse.unquote(t) for t in path[len("/playlist/"):].split(",")]
    else:
        titles = [urllib.parse.unquote(path.rsplit("/", 1)[-1])]
    src_ext = "webm" if audio else merge
    if captions and not plan:                      # the caption phase: one .vtt per item, no media
        for t in titles:
            sub = template.replace("%(title)s", t).replace("%(ext)s", sub_lang + ".vtt")
            with open(sub, "w", encoding="utf-8") as fh:
                fh.write("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\ntext\n")
            print(f"[info] Writing video subtitles to: {sub}", flush=True)
        return 0
    if plan:
        if os.environ.get("FAKE_YTDLP_PLAN_FAIL"):
            print("ERROR: plan pass failed", file=sys.stderr)
            return 1
        for t in titles:
            print("wts-plan:" + template.replace("%(title)s", t).replace("%(ext)s", src_ext), flush=True)
        return 0
    for t in titles:
        src = template.replace("%(title)s", t).replace("%(ext)s", src_ext)
        if os.path.exists(src):
            print(f"[download] {src} has already been downloaded", flush=True)
            time.sleep(float(os.environ.get("FAKE_YTDLP_SLOW", "0")))
        else:
            print(f"[download] Destination: {src}", flush=True)
            if os.environ.get("FAKE_YTDLP_DIE_PART"):
                with open(src + ".part", "wb") as fh:
                    fh.write(b"first half")
                os._exit(1)                        # the connection dropped, or the app was closed
            time.sleep(float(os.environ.get("FAKE_YTDLP_SLOW", "0")))
            old = b""
            if os.path.exists(src + ".part"):
                with open(src + ".part", "rb") as fh:
                    old = fh.read() + b"|"
                os.unlink(src + ".part")
            with open(src, "wb") as fh:
                fh.write(old + b"video:" + url.encode())
            print("[download] 100% of 1.00MiB", flush=True)
        if audio:
            final = src[: -len(src_ext)] + audio_format
            print(f"[ExtractAudio] Destination: {final}", flush=True)
            if os.environ.get("FAKE_YTDLP_FAIL_CONVERT") == t:
                with open(final, "wb") as fh:
                    fh.write(b"trunc")
                os._exit(1)
            if os.environ.get("FAKE_YTDLP_HANG_CONVERT") == t:
                with open(final, "wb") as fh:
                    fh.write(b"trunc")
                time.sleep(60)                     # a conversion the test stops from outside
            with open(final, "wb") as fh:
                fh.write(b"audio:" + url.encode())
            if not keep:
                print(f"Deleting original file {src} (pass -k to keep)", flush=True)
                os.unlink(src)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
