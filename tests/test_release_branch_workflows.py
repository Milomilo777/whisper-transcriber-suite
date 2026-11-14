"""Release candidates must receive the requested CI at their exact push SHA."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def push_branches(name: str) -> tuple[str, set[str]]:
    text = (ROOT / '.github' / 'workflows' / name).read_text(encoding='utf-8')
    events = re.search(r'^on:\n(.*?)(?=^\S)', text, re.MULTILINE | re.DOTALL)
    assert events is not None, 'Missing workflow event map'
    push = re.search(r'^  push:\n(.*?)(?=^  \w|\Z)', events[1], re.MULTILINE | re.DOTALL)
    assert push is not None, 'Missing push trigger'
    branches = re.search(r'^    branches: \[([^\]]+)\]', push[1], re.MULTILINE)
    assert branches is not None, 'Push must have an explicit branch allowlist'
    return events[1], {s.strip().strip('\"\'') for s in branches[1].split(',')}


class ReleaseBranchWorkflowTests(unittest.TestCase):
    def test_codeql_analyzes_integration_push_and_keeps_mainline(self):
        _, branches = push_branches('codeql.yml')
        self.assertIn('codex/integration-2.4.x', branches)
        self.assertIn('master', branches)

    def test_mac_packages_build_for_integration_push_and_manual_dispatch(self):
        events, branches = push_branches('macos-app.yml')
        self.assertIn('codex/integration-2.4.x', branches)
        self.assertIn('macos-app-build', branches)
        self.assertRegex(events, r'(?m)^  workflow_dispatch:')
