# Connect an AI assistant

Run `python /absolute/path/to/gui.py mcp` with the Python interpreter that has
the app's dependencies. The assistant starts it; no web server is needed.
It speaks newline-delimited UTF-8 MCP JSON-RPC and writes diagnostics to stderr.
For the Windows embedded distribution, use its `python.exe` and `gui.py`.
A frozen executable accepts `mcp` directly. Windowed Windows builds restore
inherited client pipes; a launch without stdin/stdout exits with code 2.
Packaging imports cover both transports.

## Local media and settings

Close the app and edit its `config.json` (see [configuration](CONFIG.md)):
`"mcp_allowed_folders": ["/absolute/path/to/trusted-media"]`.
On Windows use JSON-escaped paths such as `"D:\\Media"`. The default empty list
refuses all local files. Grant only folders you want an assistant to read and
write. An assistant cannot add grants. Paths must be absolute regular media
files without `..`; physical resolution refuses symlink escapes. Local files
are accepted only over stdio or HTTP from `127.0.0.1`, never a LAN peer.
Inputs are staged and results are saved beside the source with a job id and
format index in the name, preserving existing files. The server retains a
copy for `get_result`; failed local exports report an error and retain results.
Files must fit the server's bounded input size (512 MiB by default).

`get_settings` and `set_settings` expose only `whisper_model` (catalogue id),
`language` (API language code or empty for automatic), `device` (`auto`, `cpu`,
`cuda`), `compute_type`, `output_formats`, `batch_size` (1–256), `vad_enabled`,
`word_timestamps`, `diarization_enabled`, `gpu_temperature_limit_enabled`,
and `gpu_temperature_limit_c` (integer, 60–90 °C). For example:
`{"settings":{"batch_size":4,"word_timestamps":true,"language":"en"}}`.
Language is saved as `mcp_language` for subsequent assistant jobs; the GUI
language picker remains per-session. Changes use the app's normal save path.
Stdio loads the configured model for subsequent jobs; restart an already running
HTTP server after changing model, device or compute type. Install model weights
in the app first. `list_models` reports availability; no model-download tool is
provided. The temperature limit paces transcription on supported NVIDIA GPUs
when the app can read their temperature.

## Claude Desktop

In Settings → Developer → Edit Config, merge into `claude_desktop_config.json`:

```json
{"mcpServers":{"whisper":{"command":"python","args":["/absolute/path/to/gui.py","mcp"]}}}
```

Use an absolute interpreter path if `python` is not on the client's PATH, then
restart Claude Desktop. See the [official local-server guide](https://modelcontextprotocol.io/docs/2026-07-28/develop/connect-local-servers).

## Claude Code

```sh
claude mcp add --transport stdio whisper -- python /absolute/path/to/gui.py mcp
```

Use `/mcp` to inspect the connection. [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

## Codex CLI

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.whisper]
command = "python"
args = ["/absolute/path/to/gui.py", "mcp"]
```

[Codex MCP documentation](https://developers.openai.com/codex/mcp/).

## Gemini CLI

Merge the Claude Desktop JSON example above into `~/.gemini/settings.json`,
using its `mcpServers` object. Restart Gemini CLI and check `/mcp`.
[Gemini CLI MCP documentation](https://geminicli.com/docs/tools/mcp-server/).

## Cursor

Merge the same `mcpServers` example into `.cursor/mcp.json` for a project or
`~/.cursor/mcp.json` globally. Enable the server in Cursor's MCP settings.
[Cursor MCP documentation](https://docs.cursor.com/context/model-context-protocol).

## ChatGPT

Developer-mode custom connectors require a reachable HTTPS MCP URL. ChatGPT
cannot launch this local stdio command or reach the PC's loopback address.
Use the [HTTP endpoint](SERVER.md#mcp-for-ai-assistants) only behind your own
authenticated HTTPS deployment; this app does not create a public tunnel.
Remote connections cannot transcribe local paths; use public media URLs.
[OpenAI custom MCP documentation](https://developers.openai.com/api/docs/guides/custom-mcp-server).
