# Work offline: see it, and check it yourself

**File → Work offline** (or **Advanced → App behaviour**) keeps the app off the network. Which
request does what while it is on is listed in [CONFIG.md → Network use](CONFIG.md#network-use);
the code is `core/offline.py`. This page covers what the app shows while the switch is on and how
to check it with tools that do not depend on the app.

## What the app shows

While Work offline is on, a line at the bottom of the window shows one of three states:

- **No open connection to another computer (checked HH:MM:SS)**: a look at the open connections
  of the app and every process it started, at most 30 seconds old, found none. It is repeated
  every 10 seconds.
- **Open connections unknown**: there is no fresh look yet, or it failed. The app never shows
  "clean" without a fresh look.
- **WARNING, open connection to another computer**: something is open, for example a download
  that started before the switch was turned on. It names the process and the address.

The same line counts what the switch did since it was turned on: actions it refused (a link
lookup, a model download, a cloud engine) and automatic requests it did not send (the update
check, usage statistics, the online config, crash reports).

**Network log** opens a window with every refused action and connection (time, feature, host),
every automatic request that was not sent, every connection allowed because it stays on this
computer (a local AI server on `127.0.0.1`, for example), the open connections, and the limits
below. **Copy all** copies it as plain text; it holds host and feature names, no file paths.

**Verify offline now** (in the Network log) tries three things that must be refused: a TCP
connection to `203.0.113.1`, a lookup of `work-offline-check.invalid` and a UDP datagram to
`203.0.113.1`. Both names are reserved for documentation and tests (RFC 5737, RFC 6761) and reach no
real computer. Each line says `OK` (refused) or `FAILED` (not refused).

### Limits

- The counts and the event list come from the window's own process. Transcription and
  voice-clone workers install the same guard in their own process; yt-dlp, ffmpeg and the other
  helper programs are stopped by the code that starts them. Their refusals are not counted in the
  window, but their open connections are part of the 10-second check.
- The 10-second check sees what is open at that moment. A connection that opens and closes
  between two checks is not seen; the tools below see everything.
- The guard refuses outgoing TCP connections, host-name lookups (`getaddrinfo`, `gethostbyname`,
  `gethostbyaddr`, `getnameinfo`) and UDP datagrams sent with an address (`sendto`, `sendmsg`).
  Not covered: a UDP socket connected to another computer and then used with `send()`, and native
  code that does not use Python's `socket` module.
- Bytes are not measured: no reliable per-app byte count exists without administrator rights.

## Check it yourself (Windows)

Turn Work offline on, then use the app as usual: paste a link, start a transcription, open
**Help → Check for updates…**. Watch with any of these.

### Resource Monitor (no install)

1. Press **Win+R**, type `resmon`, press **Enter**.
2. Open the **Network** tab and expand **TCP Connections**.
3. Tick `pythonw.exe` (the installed app) or `python.exe` (run from source) in **Processes with
   Network Activity**. While Work offline is on, every row for it should show a **Remote Address**
   of `127.0.0.1` or `::1` (this computer), or there should be no row at all.

### PowerShell (no install)

This lists every TCP connection on the computer that goes to another computer, with the program
that owns it. Run it in a PowerShell window while you use the app:

```powershell
Get-NetTCPConnection -State Established,SynSent |
  Where-Object { $_.RemoteAddress -notmatch '^(127\.|::1$|0\.0\.0\.0$|::$)' } |
  Select-Object RemoteAddress, RemotePort, State, OwningProcess,
    @{ n = 'Program'; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } }
```

To watch for five minutes, repeat it every five seconds:

```powershell
1..60 | ForEach-Object {
  Get-NetTCPConnection -State Established,SynSent |
    Where-Object { $_.RemoteAddress -notmatch '^(127\.|::1$|0\.0\.0\.0$|::$)' } |
    Select-Object RemoteAddress, RemotePort, OwningProcess,
      @{ n = 'Program'; e = { (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName } }
  Start-Sleep -Seconds 5
}
```

No `pythonw` / `python` / `yt-dlp` / `ffmpeg` row should appear while Work offline is on (other
programs on the computer will still show theirs).

### Wireshark (optional, sees every packet)

Install [Wireshark](https://www.wireshark.org/), start a capture on the active network adapter,
use the app with Work offline on, then stop the capture. Wireshark cannot tell which program sent a
packet, so close other programs that use the network first, or compare a capture with the app
closed against one with the app in use.

## Recording a proof

A short screen recording that shows the check end to end:

1. Open the PowerShell watch loop above and Resource Monitor side by side with the app.
2. Turn **File → Work offline** on; the bottom line appears.
3. Paste a YouTube link (the lookup is refused), open **Help → Check for updates…** and answer
   **No** when it offers to turn Work offline off, start a transcription of a local file (works).
4. Open **Network log** and click **Verify offline now**: three `OK` lines.
5. Show that no app row appeared in the PowerShell window or Resource Monitor.
