"""Retired compatibility slot for overlay upgrades.

Keep this packaged path so an upgrade replaces its historical implementation
without recursively removing untracked user files. The removed capability is
not re-enabled and importing this module performs no work.
"""

__all__: tuple[str, ...] = ()
