"""Untracked application additions survive installer cleanup."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def test_uninstaller_preserves_untracked_application_subdirectories():
    text=(ROOT/'installer_embed.iss').read_text(encoding='utf-8')
    section=text.split('[UninstallDelete]',1)[1].split('[InstallDelete]',1)[0]
    recursive=[line for line in section.splitlines() if line.startswith('Type: filesandordirs;')]
    assert recursive==['Type: filesandordirs; Name: "{app}\\__pycache__"']
