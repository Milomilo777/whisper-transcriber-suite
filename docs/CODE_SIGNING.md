<!--
    type: reference
    status: current
    created: 2026-10-05
-->

# Code signing policy

**Status: the Windows releases are not code-signed yet.** The project is applying to the
[SignPath Foundation](https://signpath.org/) for its free code signing certificate for open-source
projects. Until a release's notes say that it is signed, Windows SmartScreen warns on first launch;
[INSTALL.md](INSTALL.md) shows what to click. Once signing starts, every signed release follows
this policy.

Free code signing provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

## What is signed

- The Windows installer, `WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe`, which Inno Setup
  builds from [`installer_embed.iss`](../installer_embed.iss) in this repository.

Nothing else carries the project's signature:

- The app itself is Python source code run by the bundled Python interpreter, so it has no program
  file of its own to sign.
- The Portable ZIP is an archive and cannot be signed as a whole.
- Files from other projects that the installer bundles (the Python runtime, ffmpeg and ffprobe,
  yt-dlp, Deno, and the Python packages from `requirements.txt` with their DLLs) ship unchanged,
  as their upstream projects publish them. They are never signed with this project's certificate.
- The macOS `.dmg` files are outside this policy: they stay ad-hoc signed and not notarized.

## How a signed release is made

1. GitHub Actions builds the release from a tagged commit of this repository. Files built anywhere
   else are never signed. (Today's unsigned releases are built on the maintainer's computer as
   [BUILD.md](BUILD.md) describes; the Windows build moves to GitHub Actions before the first
   signed release.)
2. The build hands the installer to SignPath.io, which checks that it came from that build of this
   repository.
3. An approver reviews each signing request and approves it by hand; nothing is signed
   automatically.
4. Signed files carry the product name "Whisper Transcriber Suite" and the release's version
   number in their file properties.

The build scripts and CI workflows in this repository are source code too: every review of a
change covers them.

## Team roles

The project has one maintainer.

- Committers and reviewers: [@Milomilo777](https://github.com/Milomilo777). Pull requests from other
  contributors are reviewed by the maintainer before they are merged.
- Approvers: [@Milomilo777](https://github.com/Milomilo777).

## Privacy policy

The app uses the network, and sends usage statistics by default after each finished transcription.
The statistics carry no audio and no transcript text; their full field list and how to turn them
off are in [CONFIG.md → Usage statistics](CONFIG.md#usage-statistics-p4-4). Every connection the
app can make, what it sends and how to stop it is listed in
[CONFIG.md → Network use](CONFIG.md#network-use). Audio or transcript text leaves the computer only
when the user picks a cloud engine or connects a remote AI provider.

Some features reach third-party services, whose own privacy policies then apply:

- GitHub: the update check, and some model and helper downloads.
  [GitHub privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)
- Hugging Face: model downloads.
  [Hugging Face privacy policy](https://huggingface.co/privacy)
- Google: YouTube when the user downloads from it, and the Gemini API or Google Cloud
  Speech-to-Text when the user selects one of them.
  [Google privacy policy](https://policies.google.com/privacy)
- PyPI: optional components installed on first use.
  [PyPI privacy notice](https://policies.python.org/pypi.org/Privacy-Notice/)
- Any other website the user downloads from, and the remote AI provider the user configures:
  that service's own policy.

## Reporting

If you think a file signed under this policy breaks it, report it to
[support@signpath.io](mailto:support@signpath.io). Security problems in the app itself:
[SECURITY.md](../SECURITY.md).
