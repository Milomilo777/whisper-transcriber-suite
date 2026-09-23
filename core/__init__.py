from __future__ import annotations

# Single bundled source of truth for the running app's version. Lives in
# the `core` package (always imported and shipped in every build,
# including the embed / frozen ones where pip package metadata isn't
# available). The About dialog and the telemetry ping read this so the
# displayed version never goes stale. Bump it alongside pyproject.toml
# and the two .iss files on every release.
__version__ = "1.9.0"
