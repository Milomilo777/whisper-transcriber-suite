"""Automated checks ensuring user documentation matches the codebase."""

import ast
import glob
import os
import re

import pytest

import core.live
import core.offline
import core.writers
from gui import _build_argparser


DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")


@pytest.fixture(scope="module")
def docs_by_file() -> dict[str, str]:
    """Returns a dict mapping markdown filename to its content."""
    docs = {}
    for md_path in glob.glob(os.path.join(DOCS_DIR, "*.md")):
        name = os.path.basename(md_path)
        with open(md_path, "r", encoding="utf-8") as f:
            docs[name] = f.read()
    return docs


@pytest.fixture(scope="module")
def user_docs_content(docs_by_file: dict[str, str]) -> str:
    """Concatenates all user-facing documentation for searching facts."""
    excludes = ["CHANGELOG.md", "DECISIONS.md"]
    content = [v for k, v in docs_by_file.items() if k not in excludes]
    return "\n".join(content)


def test_cli_flags_in_docs(user_docs_content: str) -> None:
    """Every user-settable CLI flag must be documented somewhere."""
    p = _build_argparser()
    opts = []
    for action in p._actions:
        if action.dest != "help":
            opts.extend(action.option_strings)
    if p._subparsers is not None:
        for subp in p._subparsers._group_actions[0].choices.values():
            for action in subp._actions:
                if action.dest != "help":
                    opts.extend(action.option_strings)
    
    # Handled completely outside argparse early in gui.py main()
    opts.extend(["--safe-mode"])

    missing = []
    for opt in set(opts):
        if opt not in user_docs_content:
            missing.append(opt)
    assert not missing, f"CLI flags missing from docs: {missing}"


def test_formats_in_docs(user_docs_content: str) -> None:
    """Every standard writer format must appear in the docs."""
    formats = core.writers.supported_formats()
    formats = [f for f in formats if f != "smtv_docx"]
    missing = []
    for fmt in formats:
        variations = [fmt, fmt.replace("_", " "), fmt.replace("_", "")]
        found = False
        for var in variations:
            if re.search(r'\b' + re.escape(var) + r'\b', user_docs_content, re.IGNORECASE):
                found = True
                break
        if not found:
            missing.append(fmt)
    assert not missing, f"Output formats missing from docs: {missing}"


def test_shortcuts_in_docs(user_docs_content: str) -> None:
    """Every bound keyboard shortcut must be documented."""
    # Statically extract shortcuts bound via shortcuts.bind_shortcut in app/
    app_dir = os.path.join(os.path.dirname(__file__), "..", "app")
    bound_keys = set()
    for root, _, files in os.walk(app_dir):
        for file in files:
            if not file.endswith(".py"):
                continue
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            tree = ast.parse(content, filename=filepath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute) and node.func.attr == 'bind_shortcut':
                        if (len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                                and isinstance(node.args[1].value, str)):
                            bound_keys.add(node.args[1].value)

    # Some keys map directly to characters, some to names like "Return", "Escape".
    # Check if a known representation exists in the docs.
    # We will assume a case-insensitive check of common patterns (Ctrl+O, Esc, etc.)
    missing = []
    for key in bound_keys:
        if len(key) == 1:
            pattern = rf"(Ctrl\+{key.upper()}|Cmd\+{key.upper()})"
        elif key == "Return":
            pattern = r"(Ctrl\+Enter|Cmd\+Enter)"
        elif key == "Escape":
            pattern = r"(Esc|Escape)"
        else:
            pattern = key
            
        if not re.search(pattern, user_docs_content, re.IGNORECASE):
            missing.append(key)
            
    assert not missing, f"Bound shortcuts missing from docs: {missing}"


def test_offline_behaviour_in_docs(user_docs_content: str) -> None:
    """Offline behaviour test domains/IPs from core/offline.py must be documented."""
    check_items = [core.offline.SELF_TEST_ADDRESS, core.offline.SELF_TEST_NAME]
    missing = []
    for item in check_items:
        if item not in user_docs_content:
            missing.append(item)
    assert not missing, f"Offline behaviour items missing from docs: {missing}"


def test_live_chunk_lengths_in_docs(docs_by_file: dict[str, str]) -> None:
    """The default min/max chunk lengths from SegmenterConfig must be accurately reflected in LIVE.md."""
    cfg = core.live.SegmenterConfig()
    live_md = docs_by_file.get("LIVE.md", "")
    
    max_chunk_pattern = rf"\b{int(cfg.max_chunk_s)}\s*s\b"
    min_chunk_pattern = rf"\b{int(cfg.min_chunk_s)}\s*-\s*{int(cfg.max_chunk_s)}\s*s\b"
    
    found_max = bool(re.search(max_chunk_pattern, live_md))
    found_min_max = bool(re.search(min_chunk_pattern, live_md))
    
    assert found_max and found_min_max, f"Chunk lengths {cfg.min_chunk_s} and {cfg.max_chunk_s} missing or incorrectly documented in LIVE.md"


def _slug(heading: str) -> str:
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(markdown: str) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#+ (.+)$", markdown, re.M)}


def test_relative_links_and_anchors_between_docs(docs_by_file: dict[str, str]) -> None:
    """Every relative link in the documentation must resolve to a valid file and anchor."""
    LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
    for filename, content in docs_by_file.items():
        if filename in ("CHANGELOG.md", "DECISIONS.md"):
            continue
            
        for target in LINK_RE.findall(content):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, anchor = target.partition("#")
            
            if not path:
                # Same file anchor
                own_anchors = _anchors(content)
                assert anchor in own_anchors, f"Broken link in {filename}: #{anchor}"
                continue
                
            # Path resolution
            # If path points to ../core or similar, just skip or resolve relative to docs
            target_path = os.path.normpath(os.path.join(DOCS_DIR, *path.split("/")))
            assert os.path.exists(target_path), f"Broken link in {filename}: {target} -> {target_path} not found"
            
            if anchor and target_path.endswith(".md"):
                with open(target_path, "r", encoding="utf-8") as tf:
                    target_content = tf.read()
                target_anchors = _anchors(target_content)
                assert anchor in target_anchors, f"Broken link anchor in {filename}: {target} -> #{anchor} not found in {path}"



def test_config_output_formats_complete(docs_by_file: dict[str, str]) -> None:
    """CONFIG.md's output_formats row must explicitly name all standard formats."""
    config_md = docs_by_file.get("CONFIG.md", "")
    # Find the output_formats row description cell
    m = re.search(r'\| `output_formats` \| array of strings \| .*? \| Subset of ([^|]+) \|', config_md)
    assert m is not None, "Could not find output_formats row in CONFIG.md"
    
    subset_text = m.group(1)
    
    formats = core.writers.supported_formats()
    formats = [f for f in formats if f != "smtv_docx"]
    
    missing = []
    for fmt in formats:
        # express_scribe is often written with a space
        variations = [fmt, fmt.replace("_", " ")]
        found = False
        for var in variations:
            if re.search(r'\b' + re.escape(var) + r'\b', subset_text, re.IGNORECASE):
                found = True
                break
        if not found:
            missing.append(fmt)
            
    assert not missing, f"Formats missing from CONFIG.md output_formats row: {missing}"
