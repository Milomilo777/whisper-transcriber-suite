# Preserve profiles across reinstall

The installer previously copied legacy settings and databases whenever the new
settings file was absent. The embedded uninstaller deleted that settings file
while retaining history. Together, these operations allowed a reinstall to
replace newer history with an older database. Raw SQLite copies could also omit
committed WAL data, and copying settings first prevented a later import retry.
The [Inno Setup CopyFile contract](https://jrsoftware.org/ishelp/topic_isxfunc_copyfile.htm)
confirms that a false `FailIfExists` argument overwrites an existing destination.

Both installer variants now leave profile import to the application's existing
staged settings copy and transactional SQLite merge. The embedded uninstaller
keeps settings, matching the compact variant. Product removal and the existing
optional model cleanup remain separate from profile import. Per-file copy guards
were rejected because they would still bypass WAL-aware import and retry receipts.

Source contract tests reject profile copying and settings deletion in installers.
Real SQLite tests exercise a missing settings file, an open legacy WAL, newer
destination history and idempotent import. These tests do not replace a native
upgrade, interactive uninstall and reinstall test of the final installer build.
