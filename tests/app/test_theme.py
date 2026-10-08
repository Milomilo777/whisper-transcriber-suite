"""Design tokens and the one icon set: no stray literal colours, every icon present and shipped."""
from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path

import pytest
from PIL import Image

from app.theme import icons, tokens

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "app"
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_SPECS = (
    "whisper_project_onefile.spec",
    "whisper_project_onedir.spec",
    "platform/macos/pyinstaller/whisper_project_mac.spec",
)
_INSTALLERS = ("installer_embed.iss", "installer.iss")
_ICON_SOURCE_LINE = 'Source: "assets\\icons\\*"; DestDir: "{app}\\assets\\icons"'


def _read(rel: str) -> str:
    path = _REPO / rel
    if not path.is_file():
        pytest.skip(f"{rel} is not present in this checkout")
    return path.read_text(encoding="utf-8", errors="replace")


def _hex_outside_theme() -> list[str]:
    found = []
    for path in sorted(_APP.rglob("*.py")):
        if "theme" in path.relative_to(_APP).parts[:1]:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _HEX.search(line):
                found.append(f"{path.relative_to(_REPO).as_posix()}:{number}")
    return found


# ------------------------------------------------------------------ tokens

def test_no_literal_hex_colour_outside_the_theme_package() -> None:
    assert _hex_outside_theme() == []


def test_the_hex_scan_is_not_blind() -> None:
    # Negative control: the pattern does match a literal colour in a widget call.
    assert _HEX.search('label.configure(foreground="#1a73e8")')
    assert not _HEX.search("label.configure(foreground=tokens.LINK)")


def test_every_colour_token_is_a_six_digit_hex() -> None:
    colours = {
        name: value
        for name, value in vars(tokens).items()
        if name.isupper() and isinstance(value, str)
    }
    assert colours, "no colour tokens found"
    for name, value in colours.items():
        assert _HEX.fullmatch(value), f"{name} = {value!r}"
    for table in (tokens.LIGHT, tokens.DARK):
        for name, value in table.items():
            assert _HEX.fullmatch(value), f"{name} = {value!r}"


def test_light_and_dark_define_the_same_names() -> None:
    assert set(tokens.LIGHT) == set(tokens.DARK)
    assert tokens.palette("light") is tokens.LIGHT
    assert tokens.palette("dark") is tokens.DARK
    assert tokens.palette("anything else") is tokens.DARK


def test_spacing_and_type_scales() -> None:
    assert tokens.SPACING == (4, 8, 12, 16, 24, 32)
    assert list(tokens.TYPE_SCALE) == sorted(set(tokens.TYPE_SCALE))


def test_console_colours_come_from_the_tokens() -> None:
    from app.widgets import console

    assert console._DARK["bg"] == tokens.DARK["console_bg"]
    assert console._LIGHT["error_fg"] == tokens.LIGHT["console_error_fg"]


# ------------------------------------------------------------------- icons

def _all_icon_files() -> list[tuple[str, int, float]]:
    return [(n, s, sc) for n in icons.ICON_NAMES for s in icons.LOGICAL_SIZES for sc in icons.SCALES]


def test_every_icon_exists_at_every_size_and_scale_with_the_right_pixels() -> None:
    for name, size, scale in _all_icon_files():
        path = Path(icons.icon_path(name, size, scale))
        assert path.is_file(), path
        with Image.open(path) as img:
            assert img.size == (round(size * scale),) * 2, path
            assert "A" in img.getbands(), path


def test_the_icon_folder_holds_exactly_the_declared_icons() -> None:
    expected = {icons.icon_file_name(n, s, sc) for n, s, sc in _all_icon_files()}
    pngs = {p.name for p in Path(icons.icons_dir()).glob("*.png")}
    assert pngs == expected


def test_every_icon_has_its_svg_source_and_the_licence_ships() -> None:
    sources = {p.stem for p in (_REPO / "tools" / "icons" / "lucide").glob("*.svg")}
    assert sources == set(icons.ICON_NAMES)
    licence = (Path(icons.icons_dir()) / "LICENSE-lucide.txt").read_text(encoding="utf-8")
    assert "ISC License" in licence


def test_icon_path_rejects_unknown_names_and_sizes() -> None:
    with pytest.raises(KeyError):
        icons.icon_path("no-such-icon")
    with pytest.raises(ValueError):
        icons.icon_path("play", size=17)


@pytest.mark.parametrize(
    ("asked", "shipped"),
    [(1.0, 1.0), (1.1, 1.0), (1.2, 1.25), (1.25, 1.25), (1.4, 1.5), (1.75, 2.0), (3.0, 2.0), (0.5, 1.0)],
)
def test_nearest_scale(asked: float, shipped: float) -> None:
    assert icons.nearest_scale(asked) == shipped


def test_scale_labels_match_the_file_names() -> None:
    assert icons.icon_file_name("play", 16, 1.0) == "play-16@1x.png"
    assert icons.icon_file_name("play", 24, 1.25) == "play-24@1.25x.png"


def test_tint_recolours_and_keeps_the_alpha() -> None:
    with Image.open(icons.icon_path("play", 16, 1.0)) as src:
        alpha = src.convert("RGBA").getchannel("A")
        out = icons.tint(src, "#336699")
    assert out.getchannel("A").tobytes() == alpha.tobytes()
    width, height = out.size
    pixels = out.load()
    assert pixels is not None
    opaque = [pixels[x, y] for x in range(width) for y in range(height) if pixels[x, y][3] == 255]
    assert opaque, "the icon has no fully opaque pixel"
    assert all(px[:3] == (0x33, 0x66, 0x99) for px in opaque)


def test_load_icon_returns_a_photo_image_for_the_window() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        photo = icons.load_icon(root, "download", tokens.LINK, size=16)
        assert photo.width() >= 16 and photo.height() >= 16
    finally:
        root.destroy()


# --------------------------------------------------------------- packaging

@pytest.mark.parametrize("spec", _SPECS)
def test_each_pyinstaller_spec_ships_the_whole_assets_folder(spec: str) -> None:
    text = _read(spec)
    # One data entry for the folder carries assets/icons with it.
    assert "'assets'), 'assets')" in text or "('assets', 'assets')" in text


@pytest.mark.parametrize("script", _INSTALLERS)
def test_each_installer_copies_the_icon_folder(script: str) -> None:
    if script == "installer_embed.iss":
        # Packs the whole embed_build tree; build_embed_installer.bat copies
        # assets\icons into it, so the Portable ZIP gets the icons too.
        assert 'Source: "embed_build\\*"' in _read(script)
        assert 'xcopy /I /Y "%ROOT%assets\\icons\\*" "%BUILD%\\assets\\icons\\"' in _read(
            "build_embed_installer.bat"
        )
        return
    assert _ICON_SOURCE_LINE in _read(script)

