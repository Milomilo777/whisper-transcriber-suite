# Security policy

## Supported versions

Only the latest release gets fixes. Check yours under **About**, or against
[the releases page](https://github.com/Milomilo777/whisper-transcriber-suite/releases/latest).

## Reporting a vulnerability

Please use GitHub's private reporting —
[**Report a vulnerability**](https://github.com/Milomilo777/whisper-transcriber-suite/security/advisories/new)
— rather than a public issue, and give it a few days before disclosing.

Helpful to include: the version, the OS, what an attacker would gain, and the
smallest file, URL or configuration that reproduces it.

## Retired: the bundled Google Cloud key (fixed 2026-08-04)

Windows builds from **v1.3.9 through v1.5.0** shipped a maintainer-owned
Google Cloud service-account key at `creds/gcloud_stt.json` inside the
package, so that Google Cloud Speech-to-Text worked without any setup. Because
a key was present, it also became the **default** engine — a fresh install
transcribed through the maintainer's cloud account unless the user changed it.

Why that was wrong: a credential inside a public download is a credential
handed to everyone who downloads it. It could be extracted from the package
and used outside the app entirely; all usage was billed to one project; and
that project's owner was answerable, under Google's terms, for whatever
anyone chose to transcribe with it.

What was done:

- The key was **revoked** by the maintainer. Any copy extracted from an old
  build is dead.
- Both local copies were deleted, and the build steps that copied a key into
  the package are removed — `build_embed_installer.bat` now **errors** if a
  key is sitting there, and neither PyInstaller spec adds one to `datas`.
- The default engine is unconditionally offline faster-whisper. Neither
  `core.config._default_transcribe_backend` nor
  `core.backends.availability.default_engine` looks at a bundled key any more,
  so dropping a key next to the app cannot change anyone's default.
- Regression tests in `tests/core/test_engine_selector.py` fail if either
  behaviour comes back.

If you run **v1.5.0 or older**, cloud STT will stop working; pick your own
service-account JSON in **Advanced > Backend**
([docs/CLOUD_STT_GOOGLE.md](docs/CLOUD_STT_GOOGLE.md)). Nothing else in the
app is affected — offline transcription never used the key.

**Do not re-introduce a shared credential.** If a hosted service is ever
wanted, put it behind a server the project controls, with per-user quota,
rather than a key inside the download.

## Threat model in one paragraph

This is a desktop app that reads local media files, shells out to `ffmpeg`,
`ffprobe` and `yt-dlp`, runs the speech model in a subprocess worker that talks
newline-delimited JSON over stdin/stdout, and — only when the operator turns it
on — serves an HTTP endpoint on the local network. Everything runs with the
rights of the user who launched it.

## In scope

- A crafted media file, transcript file or URL that escapes into command
  execution, or that makes the app write outside the chosen output folder and
  its own data directory.
- Anything that lets a **Web / LAN access** client read or write files outside
  the intended upload/output paths, bypass the access password, or reach the
  host beyond the documented routes.
- Leakage of the credentials used by the two opt-in cloud backends (a pasted
  Gemini API key, a Google service-account JSON) into logs, crash reports,
  transcripts or the update check.
- Tampering with the update check so it points a user at something other than
  this project's own releases.
- Privilege or persistence surprises from the installer.

## Out of scope

- Vulnerabilities in `ffmpeg`, `yt-dlp`, `faster-whisper`/`CTranslate2`, the
  bundled Python or the model weights themselves. Report those upstream; see
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- **Web / LAN access used on an untrusted network.** It is documented as
  trusted-network-only: no accounts, no TLS, an optional shared password. Anyone
  who can reach the address can use it, by design. Exposing it to the open
  internet is a deployment choice, not a bug.
- The two cloud backends uploading audio. That is their whole purpose, they are
  off by default, and both the UI and the README say so before you enable them.
- Antivirus heuristics flagging the installer or the packed executable.
