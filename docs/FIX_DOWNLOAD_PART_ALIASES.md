# Keep partial downloads separate from other files

A partial download could be a hard link to another file. Resuming it appended
bytes to both names; a restart could truncate the other file before verification.
The destination's process lock coordinates downloaders but does not establish
ownership of the partial file's contents.

Both resumable downloaders now reject partial files that are links, reparse
points, non-regular files or files with multiple hard links. Opening a file never
truncates it first: a missing path uses exclusive creation, and an existing path
uses a non-truncating mode. The open descriptor must match the inspected path
and remain a private regular file before seeking, truncating or writing. The
manifest downloader uses the same checks for restart files and prefix rollback.
Configured parent-folder aliases remain usable.

Normal resumption, ignored-range restarts, cancellation and verified publication
retain their existing behavior. Rejected aliases do not authorize modifying the
other file. These checks address existing aliases and replacement during open;
the process lock continues to coordinate cooperating downloaders.

Regression tests use real filesystem links and HTTP transfers. They check both
downloaders, ordinary private partials, links inserted during open, and a linked
restart destination after an ignored Range response. A permission-denial fixture
continues testing the same failure with the new non-truncating open mode.

The implementation uses standard [file identity/link metadata](https://docs.python.org/3.11/library/os.html#os.stat_result)
and [exclusive/non-truncating open modes](https://docs.python.org/3.11/library/functions.html#open).
