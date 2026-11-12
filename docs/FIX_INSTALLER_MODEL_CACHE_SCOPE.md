# Scope uninstall model cleanup

The uninstall hook previously offered to delete every `models--*` directory in
any configured hub. This could include other applications' models in a shared
cache. Folder names cannot establish ownership of a custom hub, so both
installer variants now retain external custom hubs and offer cleanup only for the
default local application cache. The confirmation defaults to No; other copies
may still use that cache. Application runtime directories remain subject to
normal uninstall removal; model hubs belong outside the installation folder.

The cleanup function repeats the scope check before listing models. It compares
canonical paths, requires a fixed local drive and checks every directory
ancestor from the drive downward. Unknown attributes and reparse points prevent
cleanup. The caller uses the application's standard Windows cache location;
redirected profiles are retained conservatively.

The [Windows attribute API](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileattributesw)
reports the link's attributes. The [Inno DelTree contract](https://jrsoftware.org/ishelp/topic_isxfunc_deltree.htm)
also specifies that nested reparse directories are not traversed. Native
controls preserve those targets on both the baseline and changed functions;
target deletion through such links was not reproduced.

`tools/check_installer_model_cache.py` compiles the actual cleanup functions and
uninstall callback with a supplied Inno compiler. It creates a new, marked
scratch directory, validates all resolved deletion targets inside it and tests
custom/sibling caches, directory links, unrelated files and normal private-cache
cleanup. The test setup exits before installation. Keep its fixtures and result
receipt for review. It does not replace the final installer upgrade/uninstall
test against the committed release candidate.
