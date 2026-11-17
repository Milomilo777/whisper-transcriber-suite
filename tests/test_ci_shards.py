"""Keep CI shards complete, disjoint and balanced as test files are added."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_sharder():
    spec = importlib.util.spec_from_file_location("ci_shards", ROOT / "tools/ci_shards.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_workflow_uses_three_named_shards():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "shard: [1, 2, 3]" in text
    assert "python tools/ci_shards.py --shard ${{ matrix.shard }}" in text
    assert "name: ${{ matrix.os }}" in text and "shard ${{ matrix.shard }}" in text


def test_workflow_retains_release_and_integration_coverage():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    os_expression = next(line.strip() for line in text.splitlines() if line.strip().startswith("os:"))
    assert os_expression == (
        "os: ${{ fromJSON(github.event_name == 'push' && "
        "(startsWith(github.ref, 'refs/heads/release/') || "
        "github.ref == 'refs/heads/codex/integration-2.4.x') && "
        "'[\"ubuntu-latest\"]' || '[\"windows-latest\",\"ubuntu-latest\"]') }}"
    )
    assert "python-version: [\"3.11\", \"3.12\"]" in text
    assert "exclude:\n          - os: ubuntu-latest\n            shard: 2\n          - os: ubuntu-latest\n            shard: 3" in text
    include = next(line.strip() for line in text.splitlines() if line.strip().startswith("include:"))
    assert include.startswith("include: ${{ fromJSON(github.event_name == 'push' && github.ref == 'refs/heads/codex/integration-2.4.x' && ")
    choices = re.findall(r"'(\[.*?\])'", include)
    assert json.loads(choices[0]) == [
        {"os": "windows-latest", "python-version": "3.11", "shard": n}
        for n in (1, 2, 3)
    ]
    assert json.loads(choices[1]) == []


@pytest.mark.parametrize("shard", [1, 2, 3])
def test_runner_executes_real_pytest_in_a_small_repository(tmp_path, shard):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tools/ci_shards.py").write_bytes((ROOT / "tools/ci_shards.py").read_bytes())
    (tmp_path / "tools/ci_test_durations.json").write_text("{}", encoding="utf-8")
    for i in range(6):
        (tmp_path / f"tests/test_{i}.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(tmp_path / "tools/ci_shards.py"), "--shard", str(shard)],
        cwd=tmp_path.parent, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed" in result.stdout
    assert (tmp_path / f"ci-shard-{shard}.xml").is_file()


def test_shards_cover_every_hermetic_file_exactly_once():
    sharder = load_sharder()
    expected = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "tests").rglob("*.py")
        if (p.name.startswith("test_") or p.name.endswith("_test.py"))
        and "smoke" != p.relative_to(ROOT / "tests").parts[0]
    }
    shards = sharder.split_suite(ROOT)
    counts = Counter(path for shard in shards for path in shard)
    assert set(counts) == expected
    assert set(counts.values()) == {1}
    assert all(shards)
    assert shards == sharder.split_suite(ROOT)
    assert all(shard == sorted(shard) for shard in shards)


def test_new_files_are_included_and_smoke_is_excluded(tmp_path):
    sharder = load_sharder()
    for path in ("tests/test_new.py", "tests/nested/new_test.py",
                 "tests/smoke/test_live.py", "tests/conftest.py"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    shards = sharder.split_suite(tmp_path, {})
    assert Counter(p for shard in shards for p in shard) == Counter({
        "tests/test_new.py": 1, "tests/nested/new_test.py": 1,
    })


def test_recorded_windows_durations_are_balanced():
    sharder = load_sharder()
    durations = sharder.load_durations()
    totals = [sum(durations.get(p, sharder.DEFAULT_SECONDS) for p in shard)
              for shard in sharder.split_suite(ROOT)]
    assert min(totals) > 0
    assert max(totals) / min(totals) < 1.05


@pytest.mark.parametrize("shard", [1, 2, 3])
def test_runner_passes_only_its_files_and_preserves_pytest_status(monkeypatch, shard):
    sharder = load_sharder()
    calls = []
    monkeypatch.setattr(pytest, "main", lambda args: calls.append(args) or 1)
    assert sharder.main(["--shard", str(shard)]) == 1
    args = calls.pop()
    assert args[:len(sharder.split_suite(ROOT)[shard - 1])] == sharder.split_suite(ROOT)[shard - 1]
    assert "--durations=25" in args
    assert f"--junitxml=ci-shard-{shard}.xml" in args
    assert not calls


@pytest.mark.parametrize("shard", ["0", "4"])
def test_invalid_shard_fails_before_running_tests(shard):
    with pytest.raises(SystemExit) as error:
        load_sharder().main(["--shard", shard])
    assert error.value.code == 2


def test_empty_shard_does_not_fall_back_to_the_whole_suite(monkeypatch):
    sharder = load_sharder()
    monkeypatch.setattr(sharder, "split_suite", lambda root: [[], [], []])
    with pytest.raises(SystemExit) as error:
        sharder.main(["--shard", "1"])
    assert error.value.code == 2
