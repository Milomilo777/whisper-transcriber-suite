"""Derive Store logo sizes from existing application artwork without redesign."""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path

SIZES = {"StoreLogo.png": 50, "Square44x44Logo.png": 44, "Square150x150Logo.png": 150}


def make_assets(source: Path, destination: Path) -> dict[str, str]:
    """Validate and resize artwork, writing only to a new output directory."""
    from PIL import Image, ImageOps

    source, destination = Path(source), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Asset output already exists: {destination}")
    if source.resolve().is_relative_to(destination.resolve()):
        raise ValueError("Asset output must not contain the source artwork")
    with source.open("rb") as stream:
        original = stream.read(10 * 1024 * 1024 + 1)
    if len(original) > 10 * 1024 * 1024:
        raise ValueError("Source artwork exceeds 10 MiB")
    try:
        with Image.open(io.BytesIO(original), formats=["PNG"]) as image:
            if max(image.size) > 4096:
                raise ValueError("Source artwork exceeds 4096 pixels")
            image.verify()
        with Image.open(io.BytesIO(original), formats=["PNG"]) as image:
            image.load()
            artwork = image.convert("RGBA")
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(f"Invalid application artwork: {exc}") from exc
    generated = {}
    for name, size in SIZES.items():
        resized = ImageOps.contain(artwork, (size, size), Image.Resampling.LANCZOS)
        logo = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        logo.paste(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
        buffer = io.BytesIO()
        logo.save(buffer, format="PNG")
        generated[name] = buffer.getvalue()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    for name, data in generated.items():
        with (destination / name).open("xb") as stream:
            stream.write(data)
    return {name: hashlib.sha256(data).hexdigest() for name, data in generated.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name, digest in make_assets(args.source, args.output).items():
        print(f"{digest}  {name}")


if __name__ == "__main__":
    main()
