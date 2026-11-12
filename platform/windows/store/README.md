# Microsoft Store package staging

`build_msix.py` stages an explicit **Store-specific PyInstaller ONEDIR** payload
and optionally runs the Windows SDK's MakeAppx. It never signs, installs, changes
security settings, or accesses Partner Center. The direct-download build is not
a valid input.

The payload uses the flat ONEDIR layout from `whisper_project_onedir.spec`:

- `WhisperTranscriberSuite.exe`, `bin/ffmpeg.exe`, `bin/ffprobe.exe`;
- `bin/yt-dlp.exe` and `bin/deno.exe` for the retained-download profile;
- `vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`;
- all other runtime libraries, data, model manifests and license notices;
- `STORE_BUILD.json` containing `{"schema": 1, "variant": "microsoft-store", "runtime_guards": true, "download_policy": "retain"}`.

The required binaries must have x64 PE headers. The copied private stage is
validated again before publication, including the marker and decoded PNG assets. The marker records the runtime
build's assertion; it **does not prove** that updater, download, consent or data
path guards work. Those require separate runtime tests. Known self-updater and
installer names are rejected. The explicit download profile either retains
download tools or rejects their presence; no files are silently removed. The
final download scope needs its own policy decision.
The marker's `download_policy` must match the explicit command-line profile;
`omit` requires a correspondingly built runtime marker, rather than changing
the behavior of a payload built with `retain`.

Supply PNG assets named `StoreLogo.png` (50 x 50), `Square44x44Logo.png` (44 x 44)
and `Square150x150Logo.png` (150 x 150). Pillow, already part of the application
requirements, verifies structure/CRCs and decodes the pixel data. Each file is
limited to 10 MiB and checked for exact dimensions before decoding. Use the
existing application artwork; no generated replacement
branding is required.

Run from the repository root, using new output paths:

```powershell
python platform/windows/store/build_msix.py `
  --payload path/to/store-onedir `
  --assets path/to/store-assets `
  --stage path/to/new-stage `
  --identity Example.Whisper `
  --publisher 'CN=Example' `
  --version 2.4.0.0 `
  --download-policy retain `
  --test-unsigned `
  --makeappx 'path/to/Windows SDK/x64/makeappx.exe' `
  --output path/to/new-test.msix
```

For an eventual Store submission, use the exact package identity and publisher
from Partner Center and omit `--test-unsigned`. Examples above are placeholders.
The test option adds Microsoft's unsigned-test OID and a distinct identity
suffix, so the local test package cannot impersonate the Store package. No
certificate or trust-store change is performed. See [unsigned MSIX testing](https://learn.microsoft.com/en-us/windows/msix/package/unsigned-package)
for Windows 11 installation and administrator requirements.

The manifest targets x64 Windows Desktop from build 19041 and declares
`runFullTrust`, `internetClient`, and `microphone`. No private-network capability
is declared. `internetClient` is descriptive for this full-trust desktop process;
it does not create an AppContainer or restrict its network access. See
[capability declarations](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/app-capability-declarations).

Staging sorts the file inventory, generates XML and SHA-256 records deterministically,
and normalizes file timestamps. Equal inputs produce equal staging content. Exact
MSIX byte reproducibility still needs a two-build comparison using the same SDK
version; it is not implied by a unit test. MakeAppx validation is enabled. The
stage inventory is checked before and after MakeAppx. Every actual MSIX payload
entry, including the saved inventory, is hashed against the captured stage
before publication. Duplicate, missing and unexpected entries are rejected;
only MakeAppx's generated `[Content_Types].xml` and `AppxBlockMap.xml` are allowed
in addition to the captured payload. Output publication fails
without replacing an existing package. Staging directory publication relies on
Windows' no-replacement rename behavior; use this packaging tool on Windows.

The package's installation directory is read-only. The runtime must put state in
per-user/package storage before this package is eligible for release. Verify an
installed real transcription, update restrictions, consent, clean-machine
install/uninstall and a full local [Desktop Bridge WACK run](https://learn.microsoft.com/en-us/windows/uwp/debug-test-perf/windows-desktop-bridge-app-tests)
separately. A successful MakeAppx run is not Store certification.

Windowless unit checks (requires Pillow from the build environment):

```powershell
python tests/test_store_package.py
```


## Building the Store ONEDIR payload

`whisper_project_store.spec` executes the maintained root ONEDIR specification.
Its Analysis wrapper adds the selected marker, `runtime_hook.py`, and the
`core.distribution` hidden import, while preserving the normal dependency and
resource collection. Relative root-spec inputs are resolved against the source
root. All maintained packaging specifications include the distribution-policy module;
the Store wrapper preserves standard dependency collection.

Use `build_payload.py` with an explicit Windows build interpreter containing
**PyInstaller 6.22.3** and the application's runtime/build dependencies. It does
not install packages. The selected SDK tool is recorded for the next MSIX step;
PyInstaller itself does not invoke it.

```powershell
python platform/windows/store/build_payload.py `
  --repo-root path/to/committed-source `
  --python path/to/build-environment/python.exe `
  --build-dir path/to/new-build-record `
  --dist-dir path/to/new-store-dist `
  --work-dir path/to/new-pyinstaller-work `
  --makeappx path/to/selected-sdk/makeappx.exe `
  --sdk-version 10.0.28000.2957 `
  --download-policy retain
```

All three output directories must be new and disjoint. The launcher records the
source revision, Python/dependency versions, actual source/input hashes, selected
SDK tool hash, selected policy, log and outcome in the build-record directory. It
refuses uncommitted changes unless `--scratch-fixture` is explicitly supplied;
that mode is recorded and provides no release approval. A zero tool exit is
insufficient: the ONEDIR executable and exact selected marker must exist.

The launcher freezes a new, byte-verified source snapshot under the build-record
directory and runs PyInstaller there. Original files are never made read-only or
modified. The snapshot contains the actual root Python/specification/requirements
files, `app`, `core`, `assets`, ignored `bin` payloads, `platform/windows`, source
pins and notices; Python/tool caches are excluded. This includes relevant
untracked edits in scratch mode. Update this declared scope if the root ONEDIR
specification adds a new input tree. Snapshot files are marked read-only, and
their hashes, original source revision/status/input hashes, interpreter versions
and selected tool identities are compared again before recording success. A
change leaves a failed receipt and preserves the outputs for inspection.
`SOURCE_DATE_EPOCH` comes from the source commit, and `PYTHONHASHSEED` is fixed to
`0`. Actual output reproducibility still requires repeated-build comparison.

The standalone payload must contain the exact `LICENSE` and
`THIRD_PARTY_NOTICES.md` files. The wrapper bundles both and the launcher verifies
their output bytes; Inno Setup is not involved. The final dependency license
inventory still requires review. In particular, the existing notices identify
the pinned Windows FFmpeg 9.0.2 essentials build as GPL-3.0-or-later and require
license text plus corresponding-source availability. The existing
[`platform/ffmpeg-source.json`](../../ffmpeg-source.json) records the FFmpeg 9.0.2
release source and SHA-256
`8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`.
Preserve the matching source artifact and the linked-library/build information
described in [`THIRD_PARTY_NOTICES.md`](../../../THIRD_PARTY_NOTICES.md#ffmpeg-corresponding-source)
when preparing Store distribution. Including the two notice files alone is not
a completed license/source-availability gate.

The Store wrapper filters only the unpacked
`docx/templates/default-docx-template/` source tree from the completed Analysis
data table. The python-docx runtime opens the separate packed
`docx/templates/default.docx`; that file, its other XML assets, writer templates
and notices remain included. This avoids raw OPC relationship paths such as
`_rels/.rels`, which the Windows SDK rejects as MSIX payload names with
`0x8007007b`. The staging/packing tool reports these relationship paths before
calling MakeAppx, without removing source files. See Microsoft's
[payload-file naming contract](https://learn.microsoft.com/en-us/windows/win32/api/appxpackaging/nf-appxpackaging-iappxpackagewriter-addpayloadfile)
and the [python-docx default document path](https://github.com/python-openxml/python-docx/blob/v1.2.0/src/docx/api.py).

Only `retain` payload builds are currently enabled. `omit` fails clearly until
the application's download guards are wired and tested. The sample marker files
under `fixtures/` describe both policy values for contract tests; they do not
approve either release scope or prove runtime behavior.

Derive the three logo sizes from the existing application artwork:

```powershell
python platform/windows/store/make_assets.py `
  --source assets/whisper.png --output path/to/new-store-assets
```

This preserves the artwork, aspect ratio and transparency. It creates a new
output directory and never replaces existing assets. Then pass the generated
assets and `new-store-dist/WhisperTranscriberSuite` to `build_msix.py`.

Additional windowless checks:

```powershell
python tests/test_store_build_spec.py
```

MakeAppx percent-encodes payload names inside the ZIP, including `@` in icons
and `+` in native-library names. Archive verification encodes the trusted stage
names before checking the exact member set and byte hashes. It never decodes
untrusted archive names or accepts alternate spellings of an expected member.
