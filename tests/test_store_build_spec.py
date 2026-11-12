"""Contracts for a delegated Store build and existing-artwork assets."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import stat
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "platform/windows/store"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


payload_builder = load_module("store_payload_builder", STORE / "build_payload.py")
assets_builder = load_module("store_assets_builder", STORE / "make_assets.py")


class StoreBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        (self.source / "platform/windows/store").mkdir(parents=True)
        (self.source / "core").mkdir()
        (self.source / "whisper_project_onedir.spec").write_bytes((REPO / "whisper_project_onedir.spec").read_bytes())
        (self.source / "platform/windows/store/whisper_project_store.spec").write_bytes((STORE / "whisper_project_store.spec").read_bytes())
        (self.source / "platform/windows/store/runtime_hook.py").write_text("# test hook\n", encoding="utf-8")
        (self.source / "core/distribution.py").write_text("# test policy\n", encoding="utf-8")
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            (self.source / name).write_bytes((REPO / name).read_bytes())
        self.python = self.root / "python.exe"
        self.makeappx = self.root / "makeappx.exe"
        self.python.write_bytes(b"python fixture")
        self.makeappx.write_bytes(b"SDK fixture")
        self.options = dict(repo_root=self.source, python=self.python,
            build_dir=self.root / "build", dist_dir=self.root / "dist", work_dir=self.root / "work",
            makeappx=self.makeappx, sdk_version="10.0.28000.2957", download_policy="retain")
        self.calls = []
        self.dirty = False

    def fake_run(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(command, 0, "a" * 40 + "\n", "")
        if command[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(command, 0, "?? scratch.txt\n" if self.dirty else "", "")
        if command[:2] == ["git", "show"]:
            return subprocess.CompletedProcess(command, 0, "1794300000\n", "")
        if "-c" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({"python": "3.11.10", "platform": "win32", "dependencies": {"pyinstaller": "6.22.3", "Pillow": "12.3.0"}}), "")
        payload = self.options["dist_dir"] / "WhisperTranscriberSuite"
        payload.mkdir()
        (payload / "WhisperTranscriberSuite.exe").write_bytes(b"MZfixture")
        (payload / "STORE_BUILD.json").write_bytes(Path(kwargs["env"]["WTS_STORE_MARKER_PATH"]).read_bytes())
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            (payload / name).write_bytes((self.source / name).read_bytes())
        return subprocess.CompletedProcess(command, 0)

    def build(self, **changes):
        with patch.object(payload_builder.subprocess, "run", side_effect=self.fake_run):
            return payload_builder.build_payload(**(self.options | changes))

    def test_launcher_records_inputs_and_bakes_explicit_policy(self):
        receipt = self.build()
        marker = json.loads((self.options["build_dir"] / "STORE_BUILD.json").read_text(encoding="utf-8"))
        self.assertEqual(marker, {"schema": 1, "variant": "microsoft-store", "runtime_guards": True, "download_policy": "retain"})
        self.assertEqual(receipt["source_revision"], "a" * 40)
        self.assertEqual(receipt["status"], "built")
        self.assertEqual(receipt["sdk"]["version"], "10.0.28000.2957")
        self.assertEqual(receipt["dependencies"]["pyinstaller"], "6.22.3")
        command, kwargs = next(call for call in self.calls if call[0][1:3] == ["-m", "PyInstaller"])
        self.assertEqual(command[:3], [str(self.python.resolve()), "-m", "PyInstaller"])
        self.assertNotIn("--noconfirm", command)
        self.assertEqual(Path(kwargs["env"]["WTS_STORE_MARKER_PATH"]), self.options["build_dir"] / "STORE_BUILD.json")
        self.assertEqual(Path(kwargs["env"]["PYINSTALLER_CONFIG_DIR"]), self.options["work_dir"] / "pyinstaller-config")
        self.assertEqual(kwargs["cwd"], str(self.options["build_dir"] / "source-snapshot"))
        self.assertEqual(kwargs["env"]["PYTHONHASHSEED"], "0")
        self.assertEqual(kwargs["env"]["SOURCE_DATE_EPOCH"], "1794300000")
        self.assertEqual(Path(command[-1]), self.options["build_dir"] / "source-snapshot/platform/windows/store/whisper_project_store.spec")
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)

    def test_dirty_source_requires_explicit_scratch_fixture(self):
        self.dirty = True
        with self.assertRaisesRegex(ValueError, "committed"):
            self.build()
        self.assertFalse(self.options["build_dir"].exists())
        receipt = self.build(scratch_fixture=True)
        self.assertTrue(receipt["scratch_fixture"])
        self.assertTrue(receipt["source_dirty"])

    def test_unwired_omit_policy_fails_without_creating_outputs(self):
        with self.assertRaisesRegex(ValueError, "not wired"):
            self.build(download_policy="omit")
        self.assertFalse(self.options["build_dir"].exists())
        self.assertEqual(self.calls, [])

    def test_existing_or_overlapping_output_is_preserved(self):
        self.options["dist_dir"].mkdir()
        sentinel = self.options["dist_dir"] / "original"
        sentinel.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(sentinel.read_bytes(), b"preserve")
        with self.assertRaises(ValueError):
            self.build(build_dir=self.source.parent)
        self.assertFalse(self.options["work_dir"].exists())

    def test_build_failure_keeps_receipt_and_logs_without_success(self):
        normal = self.fake_run
        def failing(command, **kwargs):
            if command[1:3] == ["-m", "PyInstaller"]:
                kwargs["stdout"].write("build failed\n")
                raise subprocess.CalledProcessError(2, command)
            return normal(command, **kwargs)
        with patch.object(payload_builder.subprocess, "run", side_effect=failing):
            with self.assertRaises(subprocess.CalledProcessError):
                payload_builder.build_payload(**self.options)
        receipt = json.loads((self.options["build_dir"] / "build-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("build failed", (self.options["build_dir"] / "pyinstaller.log").read_text(encoding="utf-8"))

    def test_zero_exit_without_payload_is_recorded_as_failure(self):
        normal = self.fake_run
        def no_payload(command, **kwargs):
            if command[1:3] == ["-m", "PyInstaller"]:
                return subprocess.CompletedProcess(command, 0)
            return normal(command, **kwargs)
        with patch.object(payload_builder.subprocess, "run", side_effect=no_payload):
            with self.assertRaisesRegex(ValueError, "did not create"):
                payload_builder.build_payload(**self.options)
        receipt = json.loads((self.options["build_dir"] / "build-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")

    def test_changed_source_during_build_is_rejected_and_recorded(self):
        normal = self.fake_run
        def changed_source(command, **kwargs):
            result = normal(command, **kwargs)
            if command[1:3] == ["-m", "PyInstaller"]:
                (self.source / "core/distribution.py").write_text("# changed policy\n", encoding="utf-8")
                self.dirty = True
            return result
        with patch.object(payload_builder.subprocess, "run", side_effect=changed_source):
            with self.assertRaisesRegex(ValueError, "changed"):
                payload_builder.build_payload(**self.options)
        receipt = json.loads((self.options["build_dir"] / "build-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")

    def test_scratch_receipt_hashes_actual_untracked_source_and_ignored_binaries(self):
        self.dirty = True
        (self.source / "bin").mkdir()
        binary = b"ignored executable fixture"
        (self.source / "bin/ffmpeg.exe").write_bytes(binary)
        scratch = b"# untracked source fixture\n"
        (self.source / "core/untracked.py").write_bytes(scratch)
        receipt = self.build(scratch_fixture=True)
        self.assertEqual(receipt["source_input_hashes"]["bin/ffmpeg.exe"], hashlib.sha256(binary).hexdigest())
        self.assertEqual(receipt["source_input_hashes"]["core/untracked.py"], hashlib.sha256(scratch).hexdigest())
        self.assertTrue(receipt["source_inputs_verified"])

    def test_ignored_binary_change_is_detected_even_if_git_state_is_unchanged(self):
        self.dirty = True
        (self.source / "bin").mkdir()
        (self.source / "bin/ffmpeg.exe").write_bytes(b"before")
        normal = self.fake_run
        def changed_binary(command, **kwargs):
            result = normal(command, **kwargs)
            if command[1:3] == ["-m", "PyInstaller"]:
                (self.source / "bin/ffmpeg.exe").write_bytes(b"after")
            return result
        with patch.object(payload_builder.subprocess, "run", side_effect=changed_binary):
            with self.assertRaisesRegex(ValueError, "changed"):
                payload_builder.build_payload(**(self.options | {"scratch_fixture": True}))

    def test_missing_license_notice_fails_before_output_creation(self):
        (self.source / "LICENSE").unlink()
        with self.assertRaisesRegex(ValueError, "LICENSE"):
            self.build()
        self.assertFalse(self.options["build_dir"].exists())

    def test_build_reads_frozen_source_when_original_is_changed_and_restored(self):
        policy = self.source / "core/distribution.py"
        original = policy.read_bytes()
        normal = self.fake_run
        def change_and_restore(command, **kwargs):
            if command[1:3] == ["-m", "PyInstaller"]:
                try:
                    policy.write_bytes(b"# transient original mutation\n")
                    self.assertEqual((Path(kwargs["cwd"]) / "core/distribution.py").read_bytes(), original)
                    return normal(command, **kwargs)
                finally:
                    policy.write_bytes(original)
            return normal(command, **kwargs)
        with patch.object(payload_builder.subprocess, "run", side_effect=change_and_restore):
            receipt = payload_builder.build_payload(**self.options)
        self.assertEqual(receipt["status"], "built")

    def test_mutated_frozen_source_is_rejected(self):
        normal = self.fake_run
        def change_snapshot(command, **kwargs):
            result = normal(command, **kwargs)
            if command[1:3] == ["-m", "PyInstaller"]:
                policy = Path(kwargs["cwd"]) / "core/distribution.py"
                policy.chmod(stat.S_IREAD | stat.S_IWRITE)
                policy.write_bytes(b"# mutated build snapshot\n")
            return result
        with patch.object(payload_builder.subprocess, "run", side_effect=change_snapshot):
            with self.assertRaisesRegex(ValueError, "snapshot changed"):
                payload_builder.build_payload(**self.options)

    def test_policy_fixtures_are_explicit_and_differ_only_by_download_scope(self):
        retain = json.loads((STORE / "fixtures/marker-retain.json").read_text(encoding="utf-8-sig"))
        omit = json.loads((STORE / "fixtures/marker-omit.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(retain, {"schema": 1, "variant": "microsoft-store", "runtime_guards": True, "download_policy": "retain"})
        self.assertEqual(omit, retain | {"download_policy": "omit"})

    def test_delegated_spec_preserves_root_build_and_adds_store_inputs(self):
        marker = self.root / "STORE_BUILD.json"
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store", "runtime_guards": True, "download_policy": "retain"}), encoding="utf-8")
        calls = []
        exe_calls = []
        # A default manifest fixture: every existing setting must survive.
        default_manifest = '''<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
          <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
            <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
          </requestedPrivileges></security></trustInfo>
          <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application>
            <supportedOS Id="fixture-os"/>
          </application></compatibility>
          <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
            <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
          </windowsSettings></application>
          <dependency><dependentAssembly><assemblyIdentity name="Microsoft.Windows.Common-Controls"
            version="6.0.0.0" type="win32" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
          </dependentAssembly></dependency>
        </assembly>'''
        def exe(*args, **kwargs):
            exe_calls.append((args, kwargs))
        keep_data = [(name, "fixture", "DATA") for name in (
            "docx/templates/default.docx", "docx/templates/default-settings.xml",
            "docx/templates/default-docx-template-old/keep.xml", "LICENSE", "THIRD_PARTY_NOTICES.md",
            "core/writers/templates/document.docx")]
        unused_data = [(name, "fixture", "DATA") for name in (
            "docx/templates/default-docx-template/_rels/.rels",
            "docx/templates/default-docx-template/word/document.xml",
            "docx\\templates\\default-docx-template\\[Content_Types].xml")]
        def analysis(*args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=keep_data + unused_data)
        hooks = ModuleType("PyInstaller.utils.hooks")
        hooks.collect_all = lambda name: ([], [], [])
        ort_notices = [(str(self.source / "onnxruntime" / name), "onnxruntime")
                       for name in ("LICENSE", "ThirdPartyNotices.txt")]
        def collect_data_files(name, **options):
            if name == "onnxruntime":
                self.assertEqual(options, {"includes": ["LICENSE", "ThirdPartyNotices.txt"]})
                return ort_notices
            return []
        hooks.collect_data_files = collect_data_files
        hooks.collect_dynamic_libs = lambda name: []
        modules = {"PyInstaller": ModuleType("PyInstaller"), "PyInstaller.utils": ModuleType("PyInstaller.utils"), "PyInstaller.utils.hooks": hooks}
        winmanifest = ModuleType("PyInstaller.utils.win32.winmanifest")
        winmanifest.create_application_manifest = lambda: default_manifest.encode("utf-8")
        modules.update({"PyInstaller.utils.win32": ModuleType("PyInstaller.utils.win32"),
                        "PyInstaller.utils.win32.winmanifest": winmanifest})
        namespace = {"SPECPATH": str(self.source / "platform/windows/store"), "Analysis": analysis,
                     "PYZ": lambda *args, **kwargs: None, "EXE": exe,
                     "COLLECT": lambda *args, **kwargs: None}
        cwd = Path.cwd()
        with patch.dict("sys.modules", modules), patch.object(importlib.util, "find_spec", return_value=SimpleNamespace()), patch.dict("os.environ", {"WTS_STORE_MARKER_PATH": str(marker)}), patch("sys.platform", "win32"):
            code = (STORE / "whisper_project_store.spec").read_text(encoding="utf-8-sig")
            exec(compile(code, str(STORE / "whisper_project_store.spec"), "exec"), namespace)
        self.assertEqual(Path.cwd(), cwd)
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[0], [str(self.source / "gui.py")])
        self.assertIn((str(marker), "."), kwargs["datas"])
        self.assertIn((str(self.source / "assets"), "assets"), kwargs["datas"])
        self.assertIn((str(self.source / "LICENSE"), "."), kwargs["datas"])
        self.assertIn((str(self.source / "THIRD_PARTY_NOTICES.md"), "."), kwargs["datas"])
        self.assertIn("core.distribution", kwargs["hiddenimports"])
        self.assertIn("core.transcriber", kwargs["hiddenimports"])
        self.assertIn(str(self.source / "platform/windows/store/runtime_hook.py"), kwargs["runtime_hooks"])
        self.assertIs(namespace["Analysis"], analysis)
        self.assertIs(namespace["EXE"], exe)
        self.assertEqual(namespace["a"].datas, keep_data)
        for notice in ort_notices:
            self.assertIn(notice, kwargs["datas"])
        self.assertEqual(len(exe_calls), 1)
        manifest = ET.fromstring(exe_calls[0][1]["manifest"])
        settings = manifest.find("{urn:schemas-microsoft-com:asm.v3}application/{urn:schemas-microsoft-com:asm.v3}windowsSettings")
        expected_dpi = {
            "{http://schemas.microsoft.com/SMI/2005/WindowsSettings}dpiAware": "true/pm",
            "{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness": "PerMonitorV2, PerMonitor",
        }
        for tag, value in expected_dpi.items():
            elements = settings.findall(tag)
            self.assertEqual(len(elements), 1)
            self.assertEqual(elements[0].text, value)
            settings.remove(elements[0])
        def structure(element):
            return element.tag, element.attrib, (element.text or "").strip(), [structure(child) for child in element]
        self.assertEqual(structure(manifest), structure(ET.fromstring(default_manifest)))
        # Execute the maintained spec directly with the restored EXE constructor.
        exe_calls.clear()
        with patch.dict("sys.modules", modules), patch.object(importlib.util, "find_spec", return_value=SimpleNamespace()), patch("sys.platform", "win32"):
            exec(compile((REPO / "whisper_project_onedir.spec").read_text(encoding="utf-8-sig"), "normal.spec", "exec"), namespace)
        self.assertEqual(len(exe_calls), 1)
        self.assertNotIn("manifest", exe_calls[0][1])

        # A present runtime must not silently lose either upstream notice.
        ort_notices.pop()
        namespace["SPECPATH"] = str(self.source / "platform/windows/store")
        with patch.dict("sys.modules", modules), patch.object(importlib.util, "find_spec", return_value=SimpleNamespace()), patch.dict("os.environ", {"WTS_STORE_MARKER_PATH": str(marker)}), patch("sys.platform", "win32"):
            with self.assertRaisesRegex(ValueError, "ONNX Runtime license notices"):
                exec(compile((REPO / "platform/windows/store/whisper_project_store.spec").read_text(encoding="utf-8"), "store.spec", "exec"), namespace)
        self.assertIs(namespace["Analysis"], analysis)
        self.assertIs(namespace["EXE"], exe)

        # A build without the optional runtime does not require its notices.
        namespace["SPECPATH"] = str(self.source / "platform/windows/store")
        with patch.dict("sys.modules", modules), patch.object(importlib.util, "find_spec", side_effect=lambda name: None if name == "onnxruntime" else SimpleNamespace()), patch.dict("os.environ", {"WTS_STORE_MARKER_PATH": str(marker)}), patch("sys.platform", "win32"):
            exec(compile((REPO / "platform/windows/store/whisper_project_store.spec").read_text(encoding="utf-8"), "store.spec", "exec"), namespace)
        self.assertFalse(any("onnxruntime" in source for source, _ in calls[-1][1]["datas"]))

    def test_spec_refuses_omit_or_missing_runtime_hook(self):
        marker = self.root / "STORE_BUILD.json"
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store", "runtime_guards": True, "download_policy": "omit"}), encoding="utf-8")
        namespace = {"SPECPATH": str(self.source / "platform/windows/store"), "Analysis": lambda: None}
        code = (STORE / "whisper_project_store.spec").read_text(encoding="utf-8-sig")
        with patch.dict("os.environ", {"WTS_STORE_MARKER_PATH": str(marker)}), patch("sys.platform", "win32"):
            with self.assertRaisesRegex(ValueError, "not wired"):
                exec(compile(code, "store.spec", "exec"), namespace)
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store", "runtime_guards": True, "download_policy": "retain"}), encoding="utf-8")
        (self.source / "platform/windows/store/runtime_hook.py").unlink()
        with patch.dict("os.environ", {"WTS_STORE_MARKER_PATH": str(marker)}), patch("sys.platform", "win32"):
            with self.assertRaisesRegex(ValueError, "runtime"):
                exec(compile(code, "store.spec", "exec"), namespace)

    def test_store_manifest_refuses_explicit_caller_metadata(self):
        marker = self.root / "STORE_BUILD.json"
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store", "runtime_guards": True, "download_policy": "retain"}), encoding="utf-8")
        code = (STORE / "whisper_project_store.spec").read_text(encoding="utf-8-sig")
        winmanifest = ModuleType("PyInstaller.utils.win32.winmanifest")
        winmanifest.create_application_manifest = lambda: b'<assembly xmlns="urn:schemas-microsoft-com:asm.v1"><application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings/></application></assembly>'
        modules = {name: ModuleType(name) for name in ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.win32")}
        modules[winmanifest.__name__] = winmanifest
        for explicit in ('<assembly><assemblyIdentity name="Custom.Identity"/></assembly>', "custom.manifest", "", None):
            with self.subTest(manifest=explicit):
                (self.source / "whisper_project_onedir.spec").write_text(f"EXE(manifest={explicit!r})\n", encoding="utf-8")
                calls = []
                def exe(*args, **kwargs):
                    calls.append(kwargs)
                analysis = lambda *args, **kwargs: None
                specpath = str(self.source / "platform/windows/store")
                namespace = {"SPECPATH": specpath, "Analysis": analysis, "EXE": exe}
                cwd = Path.cwd()
                with patch.dict("sys.modules", modules), patch.dict("os.environ", {"WTS_STORE_MARKER_PATH": str(marker)}), patch("sys.platform", "win32"):
                    if explicit is None:
                        exec(compile(code, "store.spec", "exec"), namespace)
                        self.assertEqual(len(calls), 1)
                        self.assertIn("PerMonitorV2, PerMonitor", calls[0]["manifest"])
                    else:
                        with self.assertRaisesRegex(ValueError, "explicit.*manifest"):
                            exec(compile(code, "store.spec", "exec"), namespace)
                        self.assertEqual(calls, [])
                self.assertIs(namespace["EXE"], exe)
                self.assertIs(namespace["Analysis"], analysis)
                self.assertEqual(namespace["SPECPATH"], specpath)
                self.assertEqual(Path.cwd(), cwd)

    def test_store_spec_restores_constructors_when_delegate_raises(self):
        marker = self.root / "STORE_BUILD.json"
        marker.write_text(json.dumps({"schema": 1, "variant": "microsoft-store", "runtime_guards": True, "download_policy": "retain"}), encoding="utf-8")
        (self.source / "whisper_project_onedir.spec").write_text("raise RuntimeError('delegate failed')\n", encoding="utf-8")
        code = (STORE / "whisper_project_store.spec").read_text(encoding="utf-8-sig")
        analysis = lambda *args, **kwargs: None
        exe = lambda *args, **kwargs: None
        specpath = str(self.source / "platform/windows/store")
        namespace = {"SPECPATH": specpath, "Analysis": analysis, "EXE": exe}
        cwd = Path.cwd()
        with patch.dict("os.environ", {"WTS_STORE_MARKER_PATH": str(marker)}), patch("sys.platform", "win32"):
            with self.assertRaisesRegex(RuntimeError, "delegate failed"):
                exec(compile(code, "store.spec", "exec"), namespace)
        self.assertIs(namespace["EXE"], exe)
        self.assertIs(namespace["Analysis"], analysis)
        self.assertEqual(namespace["SPECPATH"], specpath)
        self.assertEqual(Path.cwd(), cwd)


class StoreAssetTests(unittest.TestCase):
    def test_assets_derive_from_existing_artwork_and_preserve_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "artwork.png"
            image = Image.new("RGBA", (256, 256), (12, 34, 56, 255))
            image.save(source)
            original = source.read_bytes()
            result = assets_builder.make_assets(source, root / "logos")
            self.assertEqual(set(result), {"StoreLogo.png", "Square44x44Logo.png", "Square150x150Logo.png"})
            for name, size in (("StoreLogo.png", 50), ("Square44x44Logo.png", 44), ("Square150x150Logo.png", 150)):
                with Image.open(root / "logos" / name) as logo:
                    self.assertEqual(logo.size, (size, size))
                    self.assertEqual(logo.getpixel((size // 2, size // 2)), (12, 34, 56, 255))
            with self.assertRaises(FileExistsError):
                assets_builder.make_assets(source, root / "logos")
            self.assertEqual(source.read_bytes(), original)

    def test_bad_artwork_fails_without_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "bad.png"
            source.write_bytes(b"bad image")
            with self.assertRaises(ValueError):
                assets_builder.make_assets(source, root / "logos")
            self.assertFalse((root / "logos").exists())


if __name__ == "__main__":
    unittest.main()
