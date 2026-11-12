"""Stage an explicit Store ONEDIR payload and create an unsigned MSIX.

This tool does not sign, install, submit, or modify account/security settings.
The build marker is an assertion from the runtime build; guard tests are a
separate release gate, not something a marker can prove.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import quote

FOUNDATION_NS = "http://schemas.microsoft.com/appx/manifest/foundation/windows10"
UAP_NS = "http://schemas.microsoft.com/appx/manifest/uap/windows10"
RESCAP_NS = "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
UNSIGNED_OID = "OID.2.25.311729368913984317654407730594956997722=1"
REQUIRED_PAYLOAD_FILES = (
    "WhisperTranscriberSuite.exe", "bin/ffmpeg.exe", "bin/ffprobe.exe",
    "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
)
REQUIRED_RETAINED_TOOLS = ("bin/yt-dlp.exe", "bin/deno.exe")
ASSET_SIZES = {"StoreLogo.png": (50, 50), "Square44x44Logo.png": (44, 44),
               "Square150x150Logo.png": (150, 150)}
FORBIDDEN_NAMES = {"setup.exe", "update.exe", "updater.exe", "update.bat", "update.cmd"}
DOWNLOAD_TOOL_NAMES = {"yt-dlp.exe", "ytdlp.exe", "deno.exe"}


def _no_reparse(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Symlink/reparse point is not allowed: {path}")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_x64_pe(path: Path) -> None:
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError(f"Invalid required Windows binary: {path.name}")
        offset = struct.unpack_from("<I", header, 60)[0]
        if not 64 <= offset <= path.stat().st_size - 6:
            raise ValueError(f"Invalid required PE offset: {path.name}")
        stream.seek(offset)
        if stream.read(6) != b"PE\x00\x00\x64\x86":
            raise ValueError(f"Required binary must be an x64 PE file: {path.name}")


def _files(root: Path) -> list[Path]:
    _no_reparse(root)
    if not root.is_dir():
        raise ValueError(f"Expected directory: {root}")
    files = []
    def fail_walk(error: OSError) -> None:
        raise error
    for directory, directories, names in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in sorted(directories + names):
            _no_reparse(Path(directory) / name)
        for name in sorted(names):
            path = Path(directory) / name
            if not path.is_file():
                raise ValueError(f"Expected regular file: {path}")
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def _validate_png(path: Path, expected: tuple[int, int]) -> None:
    _no_reparse(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError(f"PNG asset exceeds 10 MiB: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Invalid PNG asset: {path.name}")
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("PNG validation requires Pillow; install the build requirements") from exc
    try:
        with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
            if image.size != expected:
                raise ValueError(f"Wrong PNG dimensions for {path.name}: {image.size} != {expected}")
            image.verify()
        # verify() checks structure/CRCs but does not decode IDAT pixel data.
        with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
            image.load()
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(f"Invalid PNG asset {path.name}: {exc}") from exc


def _verified_stage_inventory(stage: Path) -> dict[str, str]:
    inventory_path = stage / "payload-sha256.json"
    files = _files(stage)
    for path in files:
        _reject_reserved_relationship(path.relative_to(stage).as_posix())
    actual = {path.relative_to(stage).as_posix(): _hash(path) for path in files
              if path != inventory_path}
    try:
        expected = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Missing or invalid stage hash inventory") from exc
    if expected != actual:
        raise ValueError("Stage differs from its hash inventory")
    return actual | {"payload-sha256.json": _hash(inventory_path)}


def _reject_reserved_relationship(name: str) -> None:
    parts = name.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[-2].casefold() == "_rels" and parts[-1].casefold().endswith(".rels"):
        raise ValueError(f"MSIX reserved OPC relationship payload path: {name}; do not package unpacked document sources")


def _verify_package_archive(package: Path, expected: dict[str, str]) -> None:
    """Bind the actual unsigned MSIX payload to the captured staging bytes."""
    # Adapted from Microsoft MSIX SDK (https://github.com/microsoft/msix-packaging/blob/master/src/msix/common/Encoding.cpp) — match encoded package part names without decoding untrusted ZIP names.
    expected = {quote(name, safe="/"): digest for name, digest in expected.items()}
    generated = {"[Content_Types].xml", "AppxBlockMap.xml"}
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("MSIX archive contains duplicate entries")
            if set(names) != set(expected) | generated:
                raise ValueError("MSIX archive contains missing or unexpected entries")
            for entry in entries:
                if entry.is_dir() or entry.orig_filename != entry.filename or entry.flag_bits & 1:
                    raise ValueError("MSIX archive contains an invalid entry")
                digest = hashlib.sha256()
                with archive.open(entry) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if entry.filename in expected and digest.hexdigest() != expected[entry.filename]:
                    raise ValueError(f"MSIX archive differs from captured stage: {entry.filename}")
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid MSIX archive: {exc}") from exc


def _identity(identity: str, publisher: str, version: str, test_unsigned: bool) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9.-]{3,50}", identity):
        raise ValueError("Package identity must contain 3-50 letters, digits, dots, or hyphens")
    parts = version.split(".")
    if (len(parts) != 4 or any(not re.fullmatch(r"0|[1-9][0-9]*", part) for part in parts)
            or any(int(part) > 65535 for part in parts) or int(parts[0]) == 0 or int(parts[3]) != 0):
        raise ValueError("Store version must be major.minor.build.0 with 16-bit components and nonzero major")
    if not publisher.startswith("CN=") or len(publisher) <= 3 or any(ord(char) < 32 for char in publisher):
        raise ValueError("Publisher must be an explicit CN= distinguished name")
    if "OID.2.25." in publisher:
        raise ValueError("Supply the publisher without an unsigned OID; use --test-unsigned")
    if test_unsigned:
        identity += ".TestUnsigned"
        if len(identity) > 50:
            raise ValueError("Identity is too long for the distinct unsigned-test suffix")
        # Adapted from Microsoft MSIX documentation (https://learn.microsoft.com/en-us/windows/msix/package/unsigned-package) — unsigned test identity marker.
        publisher += ", " + UNSIGNED_OID
    return identity, publisher


def _manifest(identity: str, publisher: str, version: str, display_name: str) -> bytes:
    ET.register_namespace("", FOUNDATION_NS)
    ET.register_namespace("uap", UAP_NS)
    ET.register_namespace("rescap", RESCAP_NS)
    def element(parent, name, attrs=None, text=None):
        node = ET.SubElement(parent, f"{{{FOUNDATION_NS}}}{name}", attrs or {})
        node.text = text
        return node
    root = ET.Element(f"{{{FOUNDATION_NS}}}Package", {"IgnorableNamespaces": "uap rescap"})
    element(root, "Identity", {"Name": identity, "Publisher": publisher,
                              "Version": version, "ProcessorArchitecture": "x64"})
    properties = element(root, "Properties")
    element(properties, "DisplayName", text=display_name)
    element(properties, "PublisherDisplayName", text="Whisper Transcriber Suite")
    element(properties, "Logo", text="Assets\\StoreLogo.png")
    dependencies = element(root, "Dependencies")
    element(dependencies, "TargetDeviceFamily", {"Name": "Windows.Desktop", "MinVersion": "10.0.19041.0",
                                                "MaxVersionTested": "10.0.26100.0"})
    element(element(root, "Resources"), "Resource", {"Language": "en-us"})
    applications = element(root, "Applications")
    # Adapted from Microsoft packaging extensions documentation (https://learn.microsoft.com/en-us/windows/uwp/porting/desktop-to-uwp-extensions) — full-trust desktop entry point.
    app = element(applications, "Application", {"Id": "WhisperTranscriberSuite",
        "Executable": "app\\WhisperTranscriberSuite.exe", "EntryPoint": "Windows.FullTrustApplication"})
    ET.SubElement(app, f"{{{UAP_NS}}}VisualElements", {"DisplayName": display_name,
        "Description": "Local audio and video transcription", "BackgroundColor": "transparent",
        "Square44x44Logo": "Assets\\Square44x44Logo.png", "Square150x150Logo": "Assets\\Square150x150Logo.png"})
    caps = element(root, "Capabilities")
    # internetClient is descriptive here; medium-integrity full trust is not a network sandbox.
    element(caps, "Capability", {"Name": "internetClient"})
    ET.SubElement(caps, f"{{{RESCAP_NS}}}Capability", {"Name": "runFullTrust"})
    element(caps, "DeviceCapability", {"Name": "microphone"})
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _validate_payload(payload: Path, files: list[Path], download_policy: str) -> None:
    """Validate the runtime bytes at the supplied, private or source location."""
    required = REQUIRED_PAYLOAD_FILES + (REQUIRED_RETAINED_TOOLS if download_policy == "retain" else ())
    for relative in required:
        path = payload / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing required payload file: {relative}")
        _verify_x64_pe(path)
    marker = payload / "STORE_BUILD.json"
    try:
        build = json.loads(marker.read_text(encoding="utf-8"))
        valid_marker = (isinstance(build, dict) and type(build.get("schema")) is int
                        and build.get("schema") == 1 and build.get("variant") == "microsoft-store"
                        and build.get("runtime_guards") is True
                        and build.get("download_policy") == download_policy)
    except (OSError, ValueError):
        valid_marker = False
    if not valid_marker:
        raise ValueError("Missing or invalid Store build marker STORE_BUILD.json")
    for path in files:
        _reject_reserved_relationship(path.relative_to(payload).as_posix())
        name = path.name.lower()
        if name in FORBIDDEN_NAMES or (name.startswith("unins") and name.endswith(".exe")):
            raise ValueError(f"Known forbidden Store payload file: {path.relative_to(payload)}")
        if download_policy == "omit" and name in DOWNLOAD_TOOL_NAMES:
            raise ValueError(f"Download-omitting profile contains a forbidden tool: {path.relative_to(payload)}")


def stage_package(*, payload: Path, assets: Path, destination: Path, identity: str,
                  publisher: str, version: str, download_policy: str, test_unsigned: bool = False,
                  display_name: str = "Whisper Transcriber Suite") -> dict[str, str]:
    """Create a new staging tree; never update an existing directory.

    All runtime executables and DLLs must already be in the explicit ONEDIR
    payload. Filename exclusions catch known unwanted tools, not every possible
    downloader path; executable guard tests remain mandatory. The caller must
    explicitly select whether the payload retains or omits download tools.
    """
    payload, assets, destination = map(Path, (payload, assets, destination))
    for source in (payload, assets):
        if destination.resolve().is_relative_to(source.resolve()) or source.resolve().is_relative_to(destination.resolve()):
            raise ValueError("Destination must not overlap either input directory")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Destination already exists: {destination}")
    identity, publisher = _identity(identity, publisher, version, test_unsigned)
    if download_policy not in {"retain", "omit"}:
        raise ValueError("Download policy must be explicitly retain or omit")
    if not display_name.strip() or len(display_name) > 256 or any(ord(char) < 32 for char in display_name):
        raise ValueError("Display name must contain 1-256 printable characters")
    files = _files(payload)
    _files(assets)
    _validate_payload(payload, files, download_policy)
    for name, size in ASSET_SIZES.items():
        _validate_png(assets / name, size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".store-stage-", dir=destination.parent))
    try:
        for path in files:
            target = temporary / "app" / path.relative_to(payload)
            target.parent.mkdir(parents=True, exist_ok=True)
            before = _hash(path)
            shutil.copyfile(path, target)
            if _hash(target) != before or _hash(path) != before:
                raise ValueError(f"Input changed while staging: {path.relative_to(payload)}")
        (temporary / "Assets").mkdir()
        for name in ASSET_SIZES:
            shutil.copyfile(assets / name, temporary / "Assets" / name)
        # Publish only the bytes that passed validation in this private copy.
        # Source files can change after their initial checks and before copying.
        _validate_payload(temporary / "app", _files(temporary / "app"), download_policy)
        for name, size in ASSET_SIZES.items():
            _validate_png(temporary / "Assets" / name, size)
        (temporary / "AppxManifest.xml").write_bytes(_manifest(identity, publisher, version, display_name))
        inventory = {path.relative_to(temporary).as_posix(): _hash(path) for path in _files(temporary)}
        (temporary / "payload-sha256.json").write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        # Normalize metadata; MakeAppx reproducibility must also be verified with its exact SDK version.
        for path in _files(temporary):
            os.utime(path, (315532800, 315532800))
        if destination.exists():
            raise FileExistsError(f"Destination appeared during staging: {destination}")
        temporary.rename(destination)
        return inventory
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def pack_msix(stage: Path, output: Path, makeappx: Path) -> None:
    """Run SDK validation and publish a new package without replacing any file."""
    stage, output, makeappx = map(Path, (stage, output, makeappx))
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists: {output}")
    if not makeappx.is_file() or not (stage / "AppxManifest.xml").is_file():
        raise ValueError("MakeAppx executable and staged manifest are required")
    before = _verified_stage_inventory(stage)
    if output.resolve().is_relative_to(stage.resolve()):
        raise ValueError("Package output must be outside the stage directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".store-pack-", dir=output.parent) as folder:
        pending = Path(folder) / "package.msix"
        subprocess.run([str(makeappx.resolve()), "pack", "/d", str(stage.resolve()), "/p", str(pending), "/o"], check=True)
        if not pending.is_file() or pending.stat().st_size == 0:
            raise ValueError("MakeAppx did not produce a nonempty package")
        if _verified_stage_inventory(stage) != before:
            raise ValueError("Stage hash inventory changed during MakeAppx execution")
        _verify_package_archive(pending, before)
        # A same-volume hard link atomically fails if another writer owns output.
        os.link(pending, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--download-policy", choices=("retain", "omit"), required=True)
    parser.add_argument("--test-unsigned", action="store_true")
    parser.add_argument("--makeappx", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if bool(args.makeappx) != bool(args.output):
        parser.error("--makeappx and --output must be supplied together")
    inventory = stage_package(payload=args.payload, assets=args.assets, destination=args.stage,
        identity=args.identity, publisher=args.publisher, version=args.version,
        download_policy=args.download_policy, test_unsigned=args.test_unsigned)
    if args.makeappx:
        pack_msix(args.stage, args.output, args.makeappx)
    print(json.dumps({"staged_files": len(inventory), "package_created": bool(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
