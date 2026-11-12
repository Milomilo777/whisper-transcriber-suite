# Telemetry client privacy decisions

The November 2026 telemetry review identified lock contention during opt-out,
local diagnostic collection while statistics were off, and private words that
survived vocabulary filtering inside paths or quotes. Regression tests reproduced
these findings before the implementation changed.

The client now separates a memory-only consent generation from local state I/O.
Opt-out invalidates pending senders without waiting for either disk or HTTP.
One coalescing daemon erases the known diagnostic and rate-state files, retaining
the stable non-identifying process lock. Re-enabling waits on that cleanup in the
sender; diagnostic collection also waits. An inaccessible file can remain, and
startup with statistics off retries erasure. No durable report retry queue was
added. The final saved-preference read precedes the memory-only admission check;
HTTP runs outside both locks. An already-admitted request can finish.

Quoted spans are removed before vocabulary matching. A path-bearing token drops
the remainder of its line because file names can contain spaces. This deliberately
sacrifices diagnostic detail rather than guessing where a private name ends.
Technical codes such as WinError 5 remain useful. Independent review exposed two
additional regressions, both reproduced and fixed: opt-out during the last disk
read, and Python byte/string prefixes before a quoted title.

The three report-dialog claims now describe filtering, manual-message privacy,
and the absence of automatic retries. Obsolete translated claims were removed
without reusing their translations for different wording; these three messages
use the English fallback pending translation. Server-side admission budgets
and retention are separate changes.

## Disclosure of the expanded payload

Automatic reporting additionally requires the current local disclosure marker.
Fresh and upgraded profiles share a quiet bar; neither a previous installation ID
nor the default-on setting substitutes for showing it. The bar must be viewable
outside setup dialogs before the marker is saved. Persistence failure keeps
automatic reporting closed and offers a retry. An off choice stays off, including
when the direct off button cannot save and warns about the restart limitation.
Optional launch/crash initialization is deferred until the same disclosure gate.
While the app is running, observers read its current in-memory configuration,
including a failed-save opt-out. The Sentry delivery callback rechecks that policy;
the launch-ping worker also rejects a pre-opt-out generation after rapid off/on.
An SDK callback bound to an app that has closed or been replaced is discarded.
Manually submitted problem reports still require the separate user action.

Tests distinguish a packed bar from a mapped one, hidden startup, restarts,
remote config injection and persistence failure. Real Tk tests check focus,
widget mapping, event-loop progress and the actual off button; they do not
construct the full app or contact any telemetry service.
