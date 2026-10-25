# n8n and Obsidian: transcripts into your vault

A recipe for piping the local server's completion webhook into
[n8n](https://n8n.io) and landing transcripts as notes in an
[Obsidian](https://obsidian.md) vault. It uses only features that exist today:
the job server and its webhook ([SERVER.md](../SERVER.md)), n8n's Webhook node,
and the app's own output and watched-folder behaviour. This page is docs-only:
nothing in this repository talks to n8n or Obsidian.

## 1. Start the server and point the webhook at n8n

- Start the server shared, so other devices can reach it: in the app's
  **Web / LAN access** tab turn **Share on local network** on and click
  **Start web access**, or run `python gui.py serve --lan`. Note the LAN
  address it prints (e.g. `http://192.168.1.42:8765/`) and allow the
  firewall prompt.
- Set the tab's **Webhook URL** to n8n's production webhook URL from step 2
  (or pass `--webhook URL`). When a job finishes or fails, the server sends
  one `POST` with a JSON body: `event` (`job.finished` / `job.error`),
  `job_id`, `status`, `source`, `language`, `formats`, `outputs`
  (`[{"fmt": "srt", "name": "meeting.srt"}]`), `error` and two timestamps.
  Cancelled jobs send nothing.
- The webhook target must be `http`/`https` on another machine or a LAN
  address (`10.x`, `172.16-31.x`, `192.168.x`); the app refuses targets on
  its own loopback. If n8n runs on the same computer, use that computer's
  LAN IP — never `127.0.0.1` or `localhost`.
- Delivery is fire-and-forget: 10-second timeout, no retry, redirects are
  not followed, and the request carries no signature. Check the `job_id`
  against `GET /api/jobs/<id>` when the receiver must be picky.

## 2. Receive it in n8n

n8n must run where it can reach the app's LAN address; n8n Cloud cannot
reach a desktop, so self-host n8n on the same machine or on the LAN.

1. New workflow, add a **Webhook** node: HTTP Method `POST`, Path e.g.
   `whisper-done`, Respond `Immediately` (the app ignores the reply). The
   production URL is `http://<n8n-host>:5678/webhook/whisper-done`; put
   that in the app's **Webhook URL** field.
2. Click **Listen for test event** and finish a job to capture a sample (it
   arrives on `/webhook-test/whisper-done`); then activate the workflow so
   `/webhook/whisper-done` serves every completion.
3. The JSON body arrives under `$json.body`, e.g. `{{ $json.body.job_id }}`.
4. Add an **HTTP Request** node to fetch the transcript:
   GET `http://<lan-ip>:8765/api/jobs/{{ $json.body.job_id }}/result?fmt=txt`
   (any `fmt` listed in the webhook's `outputs` works), plus the header
   `X-Auth-Token: <access password>` when one is set.
5. If n8n runs on the machine that holds the vault, a **Read/Write Files
   from Disk** node can save the text there as a `.md` file; otherwise use
   one of the app-side recipes below.

Network notes:

- Docker n8n cannot reach the host's `127.0.0.1`: run the container with
  host networking, or keep the app shared on the LAN (step 1) and use the
  computer's LAN IP — or `host.docker.internal` — as `<lan-ip>`.
- The webhook direction is the reverse: the app dials n8n, so n8n must
  listen on an address the app can reach (n8n listens on all interfaces
  by default, hence the LAN IP above).

## 3. Obsidian recipes

Two app-side ways to file transcripts in a vault; pick one:

- **Media inside the vault.** Keep the recording or video in a folder of
  your vault and transcribe it with the desktop app, with **Markdown**
  ticked as an output format: the `.md` is written next to the media file,
  and Obsidian shows the note as soon as it lands.
- **A watched folder.** In the app's **Advanced settings…** dialog,
  **Watched folder** section, point the folder at a folder inside your
  vault and enable it. Every media file dropped there is transcribed
  automatically and its outputs are written beside it.

Both write the transcript next to the source file, so each note stays
beside its media inside the vault.
