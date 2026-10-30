from __future__ import annotations

# Single bundled source of truth for the running app's version. Lives in
# the `core` package (always imported and shipped in every build,
# including the embed / frozen ones where pip package metadata isn't
# available). The About dialog and the telemetry ping read this so the
# displayed version never goes stale. Bump it alongside pyproject.toml
# and the two .iss files on every release.
__version__ = "2.3.1"

# Sent on every HTTP request to an AI provider. Some providers (Groq, behind
# Cloudflare) answer urllib's default User-Agent with HTTP 403 "error code: 1010".
APP_USER_AGENT = f"WhisperTranscriberSuite/{__version__}"
