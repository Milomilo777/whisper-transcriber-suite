"""List possible Mach-O regular files without a subprocess per resource.

The native `file` check in verify_mac_bundle.sh confirms the candidate type
(Java class files share a fat Mach-O magic). Symlink targets are visited at
their real bundled locations, matching find -type f without following links.
"""
from pathlib import Path
import os
import stat
import sys


MAGICS = {bytes.fromhex(value) for value in (
    "feedface", "cefaedfe", "feedfacf", "cffaedfe",
    "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
)}


def candidates(root):
    def traversal_error(error):
        raise error

    for directory, _folders, files in os.walk(root, onerror=traversal_error, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if not stat.S_ISREG(os.stat(path, follow_symlinks=False).st_mode):
                continue
            with path.open("rb") as source:
                if source.read(4) in MAGICS:
                    yield path


if __name__ == "__main__":
    root = Path(sys.argv[1])
    if not root.is_dir():
        raise SystemExit("Bundle directory does not exist")
    for path in candidates(root):
        sys.stdout.buffer.write(os.fsencode(path) + b"\0")
