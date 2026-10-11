from core.updates import parse_release, pick_asset, INSTALL_WINDOWS_INSTALLER, INSTALL_WINDOWS_PORTABLE, INSTALL_MACOS_APP

# A recorded fixture of the GitHub API response for v2.0.0.
# Used to prove that the current updater parses and extracts assets correctly,
# and will remain robust for future releases adhering to the docs/BUILD.md spec.
V2_0_0_RELEASE_JSON = """{
  "tag_name": "v2.0.0",
  "html_url": "https://github.com/Milomilo777/whisper-transcriber-suite/releases/tag/v2.0.0",
  "body": "**Whisper Transcriber Suite** is a free, open-source desktop app that turns audio and video into text and subtitles with Whisper, on your own computer: no account, no upload, no per-minute cost.\\n\\n**2.0** is the biggest update yet: you see how fast each job runs and how long is left, a video link becomes an MP4 with burned-in subtitles in one step, a transcript can be shared as a single web page that works offline, and the Mac app now feels like a Mac.",
  "assets": [
    {
      "name": "WhisperTranscriberSuite-Installer-Windows-v2.0.0.exe",
      "state": "uploaded"
    },
    {
      "name": "WhisperTranscriberSuite-Portable-Windows-v2.0.0.zip",
      "state": "uploaded"
    },
    {
      "name": "WhisperTranscriberSuite-v2.0.0-macOS-arm64.dmg",
      "state": "uploaded"
    },
    {
      "name": "WhisperTranscriberSuite-v2.0.0-macOS-x64.dmg",
      "state": "uploaded"
    },
    {
      "name": "WhisperTranscriberSuite-v2.0.0-source-ffmpeg-9.0.2.tar.xz",
      "state": "uploaded"
    }
  ]
}"""

def test_parse_release_extracts_correctly() -> None:
    details = parse_release(V2_0_0_RELEASE_JSON)
    assert details.tag == "v2.0.0"
    assert "WhisperTranscriberSuite-Installer-Windows-v2.0.0.exe" in details.assets
    assert "WhisperTranscriberSuite-Portable-Windows-v2.0.0.zip" in details.assets
    assert "WhisperTranscriberSuite-v2.0.0-macOS-arm64.dmg" in details.assets

def test_pick_asset_selects_correct_files() -> None:
    details = parse_release(V2_0_0_RELEASE_JSON)

    assert pick_asset(INSTALL_WINDOWS_INSTALLER, details.assets) == "WhisperTranscriberSuite-Installer-Windows-v2.0.0.exe"
    assert pick_asset(INSTALL_WINDOWS_PORTABLE, details.assets) == "WhisperTranscriberSuite-Portable-Windows-v2.0.0.zip"

    assert pick_asset(INSTALL_MACOS_APP, details.assets, machine="arm64") == "WhisperTranscriberSuite-v2.0.0-macOS-arm64.dmg"
    assert pick_asset(INSTALL_MACOS_APP, details.assets, machine="x86_64") == "WhisperTranscriberSuite-v2.0.0-macOS-x64.dmg"
