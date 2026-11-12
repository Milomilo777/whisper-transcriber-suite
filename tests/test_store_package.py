"""Windowless contracts for Store package staging and manifest generation."""
from __future__ import annotations

import importlib.util
import hashlib
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import warnings
import xml.etree.ElementTree as ET
import zipfile
import zlib

MODULE_PATH = Path(__file__).resolve().parents[1] / "platform/windows/store/build_msix.py"
EXPECTED_PAYLOAD_FILES = ("WhisperTranscriberSuite.exe", "bin/ffmpeg.exe", "bin/ffprobe.exe",
                          "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
EXPECTED_ASSETS = {"StoreLogo.png": (50, 50), "Square44x44Logo.png": (44, 44),
                   "Square150x150Logo.png": (150, 150)}
spec = importlib.util.spec_from_file_location("store_package_builder", MODULE_PATH)
assert spec and spec.loader
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def png(width: int, height: int, idat: bytes | None = None) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00" * width * 4) * height) if idat is None else idat)
            + chunk(b"IEND", b""))


def pe() -> bytes:
    header = bytearray(64)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 60, 64)
    return bytes(header) + b"PE\x00\x00\x64\x86" + b"fixture"


def write_package(command) -> Path:
    stage = Path(command[command.index("/d") + 1])
    output = Path(command[command.index("/p") + 1])
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(stage).as_posix())
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("AppxBlockMap.xml", "<BlockMap />")
    return output


class StorePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = self.root / "payload"
        self.assets = self.root / "assets"
        self.payload.mkdir()
        self.assets.mkdir()
        for name in (*EXPECTED_PAYLOAD_FILES, "bin/yt-dlp.exe", "bin/deno.exe"):
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pe() + name.encode("ascii"))
        (self.payload / "STORE_BUILD.json").write_text(json.dumps({
            "schema": 1, "variant": "microsoft-store", "runtime_guards": True,
            "download_policy": "retain",
        }), encoding="utf-8")
        for name, size in EXPECTED_ASSETS.items():
            (self.assets / name).write_bytes(png(*size))
        self.options = dict(payload=self.payload, assets=self.assets,
                            destination=self.root / "stage", identity="Example.Whisper",
                            publisher="CN=Example", version="2.4.0.0", download_policy="retain")

    def stage(self, **changes):
        return builder.stage_package(**(self.options | changes))

    def test_sdk_percent_encoded_zip_names_match_the_original_file_bytes(self):
        cases = (
            ("app/icon@2x.png", "app/icon%402x.png"),
            ("app/libstdc++.dll", "app/libstdc%2B%2B.dll"),
            ("app/literal%2F.txt", "app/literal%252F.txt"),
            ("app/notes/\u03b4.txt", "app/notes/%CE%B4.txt"),
        )
        for index, (source_name, member_name) in enumerate(cases):
            with self.subTest(source=source_name):
                package = self.root / f"encoded-{index}.msix"
                data = b"exact staged payload"
                with zipfile.ZipFile(package, "w") as archive:
                    archive.writestr(member_name, data)
                    archive.writestr("[Content_Types].xml", "<Types />")
                    archive.writestr("AppxBlockMap.xml", "<BlockMap />")
                builder._verify_package_archive(package, {source_name: hashlib.sha256(data).hexdigest()})

    def test_encoded_members_cannot_alias_literal_percent_names_or_change_bytes(self):
        cases = (
            ("app/literal%2F.txt", "app/literal%2F.txt", b"original"),
            ("app/libstdc++.dll", "app/libstdc%2b%2b.dll", b"original"),
            ("app/libstdc++.dll", "app/libstdc%2B%2B.dll", b"changed"),
        )
        for index, (source_name, member_name, data) in enumerate(cases):
            with self.subTest(member=member_name):
                package = self.root / f"bad-encoded-{index}.msix"
                with zipfile.ZipFile(package, "w") as archive:
                    archive.writestr(member_name, data)
                    archive.writestr("[Content_Types].xml", "<Types />")
                    archive.writestr("AppxBlockMap.xml", "<BlockMap />")
                with self.assertRaisesRegex(ValueError, "MSIX archive"):
                    builder._verify_package_archive(package, {source_name: hashlib.sha256(b"original").hexdigest()})

    def test_manifest_escapes_text_and_declares_full_trust_capabilities(self):
        self.stage(display_name="Whisper & Transcriber")
        manifest = ET.parse(self.options["destination"] / "AppxManifest.xml")
        ns = {"f": builder.FOUNDATION_NS, "uap": builder.UAP_NS, "rescap": builder.RESCAP_NS}
        self.assertEqual(manifest.find("f:Properties/f:DisplayName", ns).text, "Whisper & Transcriber")
        app = manifest.find("f:Applications/f:Application", ns)
        self.assertEqual(app.attrib["Executable"], "app\\WhisperTranscriberSuite.exe")
        self.assertEqual(app.attrib["EntryPoint"], "Windows.FullTrustApplication")
        capabilities = manifest.find("f:Capabilities", ns)
        self.assertEqual({node.attrib["Name"] for node in capabilities},
                         {"runFullTrust", "internetClient", "microphone"})
        self.assertEqual(manifest.find("f:Identity", ns).attrib["Publisher"], "CN=Example")

    def _mutate_after_asset_validation(self, mutate):
        validate = builder._validate_png
        calls = 0
        def hook(path, size):
            nonlocal calls
            validate(path, size)
            calls += 1
            if calls == len(EXPECTED_ASSETS):
                mutate()
        return patch.object(builder, "_validate_png", side_effect=hook)

    def test_marker_mutation_after_validation_cannot_publish(self):
        def mutate():
            (self.payload / "STORE_BUILD.json").write_text("{}", encoding="utf-8")
        with self._mutate_after_asset_validation(mutate):
            with self.assertRaisesRegex(ValueError, "marker|changed"):
                self.stage()
        self.assertFalse(self.options["destination"].exists())

    def test_binary_mutation_after_validation_cannot_publish(self):
        def mutate():
            (self.payload / "WhisperTranscriberSuite.exe").write_bytes(pe().replace(b"\x64\x86", b"\x4c\x01"))
        with self._mutate_after_asset_validation(mutate):
            with self.assertRaisesRegex(ValueError, "x64|changed"):
                self.stage()
        self.assertFalse(self.options["destination"].exists())

    def test_png_mutation_after_validation_cannot_publish(self):
        def mutate():
            (self.assets / "StoreLogo.png").write_bytes(b"invalid PNG")
        with self._mutate_after_asset_validation(mutate):
            with self.assertRaises(ValueError):
                self.stage()
        self.assertFalse(self.options["destination"].exists())

    def _assert_retained_tool_rejected(self, relative, *, wrong_arch=False):
        path = self.payload / relative
        if wrong_arch:
            path.write_bytes(pe().replace(b"\x64\x86", b"\x4c\x01"))
        else:
            path.unlink()
        with self.assertRaisesRegex(ValueError, "required|x64"):
            self.stage()
        self.assertFalse(self.options["destination"].exists())

    def test_retain_requires_ytdlp(self):
        self._assert_retained_tool_rejected("bin/yt-dlp.exe")

    def test_retain_requires_deno(self):
        self._assert_retained_tool_rejected("bin/deno.exe")

    def test_retain_rejects_x86_ytdlp(self):
        self._assert_retained_tool_rejected("bin/yt-dlp.exe", wrong_arch=True)

    def test_retain_rejects_x86_deno(self):
        self._assert_retained_tool_rejected("bin/deno.exe", wrong_arch=True)

    def test_two_stages_have_identical_manifests_and_hash_inventory(self):
        first = self.stage()
        second = self.stage(destination=self.root / "stage2")
        self.assertEqual(first, second)
        for name in ("AppxManifest.xml", "payload-sha256.json"):
            self.assertEqual((self.root / "stage" / name).read_bytes(), (self.root / "stage2" / name).read_bytes())
        self.assertEqual((self.root / "stage/app/bin/ffmpeg.exe").read_bytes(),
                         (self.payload / "bin/ffmpeg.exe").read_bytes())

    def test_missing_tools_or_runtime_fail_before_creating_destination(self):
        for name in EXPECTED_PAYLOAD_FILES:
            path = self.payload / name
            saved = path.read_bytes()
            path.unlink()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "required"):
                self.stage()
            self.assertFalse(self.options["destination"].exists())
            path.write_bytes(saved)

    def test_wrong_architecture_is_rejected_before_staging(self):
        (self.payload / "WhisperTranscriberSuite.exe").write_bytes(pe().replace(b"\x64\x86", b"\x4c\x01"))
        with self.assertRaisesRegex(ValueError, "x64"):
            self.stage()
        self.assertFalse(self.options["destination"].exists())

    def test_absent_or_invalid_build_marker_is_rejected(self):
        marker = self.payload / "STORE_BUILD.json"
        for value in (None, {}, {"schema": 1, "variant": "direct"},
                      {"schema": 1, "variant": "microsoft-store", "runtime_guards": False},
                      {"schema": True, "variant": "microsoft-store", "runtime_guards": True}):
            if value is None:
                marker.unlink()
            else:
                marker.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "marker"):
                self.stage()
            self.assertFalse(self.options["destination"].exists())

    def test_forbidden_installer_and_updater_payloads_fail_closed(self):
        for name in ("update.bat", "nested/setup.exe"):
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not for Store")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "forbidden"):
                self.stage()
            path.unlink()

    def test_download_profile_is_explicit_and_does_not_silently_remove_tools(self):
        tool = self.payload / "bin/yt-dlp.exe"
        tool.write_bytes(pe() + b"download tool")
        marker = self.payload / "STORE_BUILD.json"
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store",
                                      "runtime_guards": True, "download_policy": "omit"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "forbidden"):
            self.stage(download_policy="omit")
        self.assertTrue(tool.exists())
        self.assertFalse(self.options["destination"].exists())
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store",
                                      "runtime_guards": True, "download_policy": "retain"}), encoding="utf-8")
        self.stage(download_policy="retain")
        self.assertEqual((self.options["destination"] / "app/bin/yt-dlp.exe").read_bytes(), pe() + b"download tool")

    def test_unknown_download_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "policy"):
            self.stage(download_policy="guess")

    def test_reserved_opc_relationship_payload_fails_before_staging(self):
        for name in ("docx/templates/default-docx-template/_rels/.rels", "nested/_rels/relationships.rels"):
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"relationship source; must not be a raw MSIX payload")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "reserved.*relationship"):
                self.stage()
            self.assertFalse(self.options["destination"].exists())
            self.assertTrue(path.exists())
            path.unlink()

    def test_existing_stage_reserved_relationship_is_rejected_before_sdk(self):
        inventory = self.stage()
        stage = self.options["destination"]
        path = stage / "app/nested/_rels/.rels"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"reserved relationship")
        inventory[path.relative_to(stage).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        (stage / "payload-sha256.json").write_text(json.dumps(inventory), encoding="utf-8")
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        with patch.object(builder.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "reserved.*relationship"):
                builder.pack_msix(stage, self.root / "out.msix", tool)
            run.assert_not_called()
        self.assertTrue(path.exists())

    def test_marker_download_policy_must_match_selected_profile(self):
        with self.assertRaisesRegex(ValueError, "marker"):
            self.stage(download_policy="omit")
        marker = self.payload / "STORE_BUILD.json"
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store", "runtime_guards": True}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "marker"):
            self.stage()

    def test_existing_destination_and_source_overlap_are_rejected(self):
        destination = self.options["destination"]
        destination.mkdir()
        sentinel = destination / "original"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.stage()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        for path in (self.payload / "nested", self.root, self.assets / "nested"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.stage(destination=path)

    def test_invalid_identity_version_publisher_and_asset_are_rejected(self):
        for changes in ({"identity": "bad/name"}, {"identity": "x"}, {"version": "2.4"},
                        {"version": "2.4.0.1"}, {"version": "65536.0.0.0"},
                        {"publisher": ""}, {"publisher": "not distinguished name"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.stage(**changes)
        (self.assets / "StoreLogo.png").write_bytes(png(1, 1))
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.stage()
        self.assertFalse(self.options["destination"].exists())

    def test_unsigned_test_identity_has_required_marker_and_is_distinct(self):
        self.stage(test_unsigned=True)
        manifest = ET.parse(self.options["destination"] / "AppxManifest.xml")
        ident = manifest.find(f"{{{builder.FOUNDATION_NS}}}Identity")
        self.assertTrue(ident.attrib["Publisher"].endswith(builder.UNSIGNED_OID))
        self.assertTrue(ident.attrib["Name"].endswith(".TestUnsigned"))

    def test_reparse_points_are_rejected_without_reading_their_target(self):
        fake_stat = type("Stat", (), {"st_file_attributes": 0x400, "st_mode": 0})()
        with patch.object(builder.Path, "lstat", return_value=fake_stat):
            with self.assertRaisesRegex(ValueError, "reparse"):
                self.stage()

    def test_invalid_pixel_stream_is_rejected_before_staging(self):
        (self.assets / "StoreLogo.png").write_bytes(png(50, 50, idat=b"not a zlib stream"))
        with self.assertRaisesRegex(ValueError, "PNG"):
            self.stage()
        self.assertFalse(self.options["destination"].exists())

    def test_unreadable_subdirectory_is_not_silently_omitted(self):
        native = self.payload / "native"
        native.mkdir()
        (native / "required.dll").write_bytes(pe())
        real_scandir = builder.os.scandir
        def blocked_scandir(path):
            if Path(path) == native:
                raise PermissionError("unreadable native payload")
            return real_scandir(path)
        with patch.object(builder.os, "scandir", side_effect=blocked_scandir):
            with self.assertRaises(PermissionError):
                self.stage()
        self.assertFalse(self.options["destination"].exists())

    def test_makeappx_uses_argument_vector_and_preserves_existing_output(self):
        stage = self.options["destination"]
        self.stage()
        tool = self.root / "Make Appx.exe"
        tool.write_bytes(b"tool")
        output = self.root / "Whisper.msix"
        def fake_run(command, **kwargs):
            self.assertEqual(command[0], str(tool.resolve()))
            self.assertEqual(command[1:3], ["pack", "/d"])
            self.assertNotIn("/nv", command)
            write_package(command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(builder.subprocess, "run", side_effect=fake_run) as run:
            builder.pack_msix(stage, output, tool)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("app/bin/ffmpeg.exe"), (stage / "app/bin/ffmpeg.exe").read_bytes())
            with self.assertRaises(FileExistsError):
                builder.pack_msix(stage, output, tool)
            self.assertEqual(run.call_count, 1)

    def test_failed_pack_never_publishes_output(self):
        self.stage()
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        output = self.root / "Whisper.msix"
        with patch.object(builder.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "makeappx")):
            with self.assertRaises(subprocess.CalledProcessError):
                builder.pack_msix(self.options["destination"], output, tool)
        self.assertFalse(output.exists())

    def test_pack_rejects_changed_stage_before_running_tool(self):
        self.stage()
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        (self.options["destination"] / "app/bin/ffmpeg.exe").write_bytes(b"changed")
        with patch.object(builder.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "inventory"):
                builder.pack_msix(self.options["destination"], self.root / "out.msix", tool)
            run.assert_not_called()

    def test_pack_rejects_stage_changed_during_tool_execution(self):
        self.stage()
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        output = self.root / "out.msix"
        def fake_run(command, **kwargs):
            (self.options["destination"] / "app/bin/ffmpeg.exe").write_bytes(b"changed during pack")
            write_package(command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(builder.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "inventory"):
                builder.pack_msix(self.options["destination"], output, tool)
        self.assertFalse(output.exists())

    def test_pack_publication_race_preserves_other_writer(self):
        self.stage()
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        output = self.root / "out.msix"
        def fake_run(command, **kwargs):
            write_package(command)
            output.write_bytes(b"other writer")
            return subprocess.CompletedProcess(command, 0)
        with patch.object(builder.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(FileExistsError):
                builder.pack_msix(self.options["destination"], output, tool)
        self.assertEqual(output.read_bytes(), b"other writer")

    def test_pack_rejects_hash_receipt_changed_during_tool_execution(self):
        self.stage()
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        output = self.root / "out.msix"
        def fake_run(command, **kwargs):
            inventory = self.options["destination"] / "payload-sha256.json"
            inventory.write_bytes(inventory.read_bytes() + b" ")
            write_package(command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(builder.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "inventory"):
                builder.pack_msix(self.options["destination"], output, tool)
        self.assertFalse(output.exists())

    def test_pack_rejects_changed_archive_even_when_stage_is_restored(self):
        self.stage()
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        output = self.root / "out.msix"
        target = self.options["destination"] / "app/bin/ffmpeg.exe"
        original = target.read_bytes()
        def fake_run(command, **kwargs):
            try:
                target.write_bytes(b"wrong archived runtime")
                write_package(command)
            finally:
                target.write_bytes(original)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(builder.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(ValueError, "archive"):
                builder.pack_msix(self.options["destination"], output, tool)
        self.assertFalse(output.exists())
        self.assertEqual(target.read_bytes(), original)

    def test_pack_rejects_duplicate_or_unexpected_archive_members(self):
        self.stage()
        tool = self.root / "makeappx.exe"
        tool.write_bytes(b"tool")
        output = self.root / "out.msix"
        for name in ("app/bin/ffmpeg.exe", "../outside.txt", "AppxSignature.p7x"):
            def fake_run(command, **kwargs):
                pending = write_package(command)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(pending, "a") as archive:
                        archive.writestr(name, "unexpected")
                return subprocess.CompletedProcess(command, 0)
            with self.subTest(name=name), patch.object(builder.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(ValueError, "archive"):
                    builder.pack_msix(self.options["destination"], output, tool)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
