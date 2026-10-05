# Windows — updating a source install

```cmd
platform\windows\update.bat
```

Pulls the latest source and refreshes the Python dependencies. The
counterpart to [`platform/linux/update.sh`](../linux/update.sh), which
Linux has shipped since v1.3.

## Which kind of install do you have?

| You installed with | How you update |
|---|---|
| **`Setup-Standard.exe`** | Download the newer installer and run it. It upgrades in place and keeps your shortcut and settings. **Do not** use this script. |
| **`Portable.zip`** | Replace the old folder with the new one. **Do not** use this script. |
| **`git clone`** (source) | This script. |

## What it does

1. `git pull --ff-only` when the folder is a git checkout (skipped
   otherwise, and skipped with a warning if `git` is not on `PATH`).
2. Upgrades `pip` and everything in `requirements.txt`. A `.venv` next to
   the source is preferred over the system Python, so packages land where
   a source install put them.
3. Runs `bin\yt-dlp.exe -U` when that binary is present. A stale `yt-dlp`
   is the single most common cause of "downloads suddenly stopped
   working" — sites change their players constantly.
4. **Verifies the app still imports.** A dependency resolver conflict can
   report success and still leave a tree that will not start; failing
   here is much better than failing on the next launch.

Exit code `0` on success, `1` on failure. It refuses to run at all if
`gui.py` is missing, so it cannot be pointed at an installed copy of the
app by mistake.

## Why the app does not update itself

`core/updates.py` is deliberately **notify-only**: it asks GitHub once a
day whether a newer release exists and, if so, shows a quiet bar whose
**Download** button opens the matching file in the browser. It never
downloads or installs anything itself.

An installed application that rewrites its own files is a support
nightmare — a half-applied update leaves a user with nothing that runs,
and on Windows it fights the installer's own upgrade path, file locks and
antivirus heuristics. Updating an *installed* build stays the installer's
job. This script exists only for the source install, where "update" is
honestly just `git pull` plus `pip install -U`.

Turn the notification off under **Advanced → App behaviour** ("Don't check
for updates", config key `update_check_enabled`) or with the environment
variable `WTS_DISABLE_UPDATER=1` — see [docs/CONFIG.md](../../docs/CONFIG.md).
On a source install its **Download** button shows the command that runs this
script.
