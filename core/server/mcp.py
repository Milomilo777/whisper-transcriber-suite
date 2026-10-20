"""Model Context Protocol (MCP) dispatcher for the local HTTP API.

``POST /mcp`` (core/server/httpd.py) hands each decoded JSON-RPC message to
:func:`handle`, which answers it without any I/O of its own beyond the job
manager calls and reading a finished job's text output. It implements the
server side of MCP revision 2025-06-18 over the Streamable HTTP transport in
its simplest form: one JSON response per POST, no SSE stream, no session
(``Mcp-Session-Id`` is optional in that revision and this server keeps no
per-client state).

The tools mirror the JSON job API: ``transcribe_url`` goes through the same
validators as ``POST /api/jobs`` (normalize_formats, normalize_language,
english_only_problem, parse_clip and the manager's is_safe_url gate), but
refuses a value those validators would replace instead of dropping it
silently. No tool takes a local file path: a remote client must never be
able to make the server read files from this computer.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Callable

from core.server.jobs import STATUS_FINISHED, QueueFull
from core.writers import BINARY_WRITERS, extension_for, supported_formats

logger = logging.getLogger(__name__)

# Newest first. 2025-03-26 introduced the Streamable HTTP transport; the
# older 2024-11-05 revision used HTTP+SSE, which this endpoint does not speak,
# so a client asking for it is offered the newest revision instead.
PROTOCOL_VERSIONS: tuple[str, ...] = ("2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = PROTOCOL_VERSIONS[0]

SERVER_NAME = "whisper-transcriber-suite"

# JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Request methods this server answers (notifications need no entry).
METHODS: frozenset[str] = frozenset({"initialize", "ping", "tools/list",
                                     "tools/call"})

_DEFAULT_URL_FORMATS = ["txt"]


def error_response(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    """A JSON-RPC error object (``msg_id`` None when it is unknown)."""
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


class _ToolError(Exception):
    """A tool failure, reported as a result with ``isError: true``."""


def _tool_result(data: dict[str, Any] | None = None, *,
                 text: str | None = None) -> dict[str, Any]:
    """A successful tool result: JSON in structuredContent plus a text copy."""
    out: dict[str, Any] = {"isError": False}
    if data is not None:
        out["structuredContent"] = data
        text = json.dumps(data, ensure_ascii=False)
    out["content"] = [{"type": "text", "text": text or ""}]
    return out


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


# --- tool definitions ----------------------------------------------------------

def _schema(properties: dict[str, Any],
            required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties,
                              "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


_JOB_ID = {"type": "string", "description": "A job id from transcribe_url "
                                            "or list_jobs."}


def tool_definitions() -> list[dict[str, Any]]:
    """The tools/list payload; the format enums follow the writer registry."""
    formats = supported_formats()
    return [
        {
            "name": "transcribe_url",
            "description": (
                "Queue a transcription of an http(s) media link (a video or "
                "audio page or file). Returns the job id; poll job_status, "
                "then read the text with get_result. Links to this computer "
                "itself are refused."),
            "inputSchema": _schema({
                "url": {"type": "string",
                        "description": "http(s) link to the media."},
                "language": {
                    "type": ["string", "null"],
                    "description": ("Spoken language as an ISO 639-1 code "
                                    "(for example 'en', 'fa'); omit, null or "
                                    "'' to auto-detect.")},
                "formats": {
                    "type": "array", "minItems": 1,
                    "items": {"type": "string", "enum": formats},
                    "default": list(_DEFAULT_URL_FORMATS),
                    "description": "Output formats to write."},
                "clip_start": {"type": "number", "minimum": 0,
                               "description": "Start of the part to "
                                              "transcribe, in seconds."},
                "clip_end": {"type": "number", "exclusiveMinimum": 0,
                             "description": "End of the part to transcribe, "
                                            "in seconds."},
            }, ["url"]),
        },
        {
            "name": "job_status",
            "description": ("Status of one job: status, progress (0-100), "
                            "error and the outputs written so far."),
            "inputSchema": _schema({"job_id": _JOB_ID}, ["job_id"]),
        },
        {
            "name": "get_result",
            "description": (
                "Text of one output of a finished job. Binary formats "
                "(docx, pdf) are not returned here: download them from the "
                "HTTP route /api/jobs/<id>/result?fmt=<format>."),
            "inputSchema": _schema({
                "job_id": _JOB_ID,
                "format": {"type": "string", "enum": formats,
                           "default": "txt"},
            }, ["job_id"]),
        },
        {
            "name": "list_jobs",
            "description": "Recent jobs of this server, newest first.",
            "inputSchema": _schema({}),
        },
        {
            "name": "cancel_job",
            "description": "Cancel a queued or running job.",
            "inputSchema": _schema({"job_id": _JOB_ID}, ["job_id"]),
        },
    ]


# --- argument validation ---------------------------------------------------------

def _check_keys(args: dict[str, Any], allowed: tuple[str, ...]) -> None:
    extra = sorted(str(k) for k in args if k not in allowed)
    if extra:
        raise _ToolError(
            f"unknown argument(s): {', '.join(extra)}; this tool accepts: "
            f"{', '.join(allowed) or 'none'}")


def _job_id(args: dict[str, Any]) -> str:
    job_id = args.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise _ToolError("job_id is required and must be a non-empty string")
    return job_id.strip()


def _clip_value(args: dict[str, Any], key: str) -> float | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _ToolError(f"{key} must be a number of seconds")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise _ToolError(f"{key} must be a finite number >= 0")
    return number


def validate_transcribe_args(
        args: dict[str, Any]) -> tuple[str, list[str], str,
                                       float | None, float | None]:
    """(url, formats, language, clip_start, clip_end) or a ``_ToolError``.

    Every value passes the same normaliser POST /api/jobs uses; a value the
    normaliser would drop or replace is refused instead, because an assistant
    that sent it expects it to take effect.
    """
    from core.server import httpd  # httpd imports this module

    _check_keys(args, ("url", "language", "formats", "clip_start",
                       "clip_end"))
    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        raise _ToolError("url is required and must be a non-empty string")
    url = url.strip()

    raw_formats = args.get("formats", _DEFAULT_URL_FORMATS)
    if (not isinstance(raw_formats, list) or not raw_formats
            or not all(isinstance(f, str) for f in raw_formats)):
        raise _ToolError("formats must be a non-empty list of format names")
    known = set(supported_formats())
    unknown = [f for f in raw_formats if f.strip().lower() not in known]
    if unknown:
        raise _ToolError(
            f"unsupported format(s): {', '.join(unknown)}; supported: "
            f"{', '.join(sorted(known))}")
    formats = httpd.normalize_formats(raw_formats)

    raw_language = args.get("language")
    if raw_language is None:
        raw_language = ""
    if not isinstance(raw_language, str):
        raise _ToolError("language must be a string such as 'en', or null")
    language = httpd.normalize_language(raw_language)
    if raw_language.strip() and not language:
        raise _ToolError(
            f"unsupported language {raw_language!r}; use one of: "
            f"{', '.join(c for c in httpd.WEB_LANGUAGE_CODES if c)}, "
            "or omit it to auto-detect")
    problem = httpd.english_only_problem(language)
    if problem:
        raise _ToolError(problem)

    raw_start = _clip_value(args, "clip_start")
    raw_end = _clip_value(args, "clip_end")
    if raw_end is not None and raw_end <= 0:
        raise _ToolError("clip_end must be greater than 0")
    if (raw_start is not None and raw_end is not None
            and raw_end <= raw_start):
        raise _ToolError("clip_end must be greater than clip_start")
    clip_start, clip_end = httpd.parse_clip(raw_start, raw_end)
    return url, formats, language, clip_start, clip_end


# --- tools -------------------------------------------------------------------------

def _transcribe_url(args: dict[str, Any], manager: Any) -> dict[str, Any]:
    url, formats, language, clip_start, clip_end = (
        validate_transcribe_args(args))
    try:
        from core.server.httpd import job_language_model

        # Only when a language model is chosen (ADR 0016), so other managers keep working.
        chosen = job_language_model(language)
        extra = {"language_model": chosen} if chosen[0] else {}
        job_id = manager.submit_url(url, formats, language, options={},
                                    clip_start=clip_start, clip_end=clip_end, **extra)
    except (ValueError, QueueFull) as exc:
        raise _ToolError(str(exc)) from None
    return _tool_result({"job_id": job_id})


def _job_status(args: dict[str, Any], manager: Any) -> dict[str, Any]:
    _check_keys(args, ("job_id",))
    job_id = _job_id(args)
    job = manager.get(job_id)
    if job is None:
        raise _ToolError(f"no such job: {job_id}")
    return _tool_result(job.public_dict())


def _list_jobs(args: dict[str, Any], manager: Any) -> dict[str, Any]:
    _check_keys(args, ())
    return _tool_result({"jobs": manager.list()})


def _is_binary_format(fmt: str) -> bool:
    return fmt in BINARY_WRITERS or fmt in {extension_for(k)
                                            for k in BINARY_WRITERS}


def _get_result(args: dict[str, Any], manager: Any) -> dict[str, Any]:
    _check_keys(args, ("job_id", "format"))
    job_id = _job_id(args)
    raw_fmt = args.get("format", "txt")
    if not isinstance(raw_fmt, str) or (
            raw_fmt.strip().lower() not in set(supported_formats())):
        raise _ToolError(f"unsupported format {raw_fmt!r}; supported: "
                         f"{', '.join(supported_formats())}")
    fmt = raw_fmt.strip().lower()
    job = manager.get(job_id)
    if job is None:
        raise _ToolError(f"no such job: {job_id}")
    if job.status != STATUS_FINISHED:
        raise _ToolError(f"job {job_id} is not finished (status: "
                         f"{job.status})")
    route = f"/api/jobs/{job_id}/result?fmt={fmt}"
    if _is_binary_format(fmt):
        raise _ToolError(f"'{fmt}' is a binary format; download it over "
                         f"HTTP from {route}")
    path = manager.output_path(job_id, fmt)
    if not path:
        raise _ToolError(f"job {job_id} has no '{fmt}' output; ask for one "
                         "of the formats job_status lists")
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as exc:
        logger.warning("mcp: cannot read %s: %s", path, exc)
        raise _ToolError(f"the '{fmt}' output of job {job_id} cannot be "
                         f"read: {exc.strerror or exc}") from None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _ToolError(f"the '{fmt}' output is not UTF-8 text; download "
                         f"it over HTTP from {route}") from None
    return _tool_result(text=text)


def _cancel_job(args: dict[str, Any], manager: Any) -> dict[str, Any]:
    _check_keys(args, ("job_id",))
    job_id = _job_id(args)
    if not manager.cancel(job_id):
        raise _ToolError(f"no such active job: {job_id} (finished, "
                         "cancelled or unknown)")
    return _tool_result({"cancelled": job_id})


_TOOLS: dict[str, Callable[[dict[str, Any], Any], dict[str, Any]]] = {
    "transcribe_url": _transcribe_url,
    "job_status": _job_status,
    "get_result": _get_result,
    "list_jobs": _list_jobs,
    "cancel_job": _cancel_job,
}


# --- dispatch ------------------------------------------------------------------------

def _valid_id(value: Any) -> bool:
    # MCP: "a string or integer", never null (JSON-RPC also allows fractional
    # numbers and null; MCP narrows that).
    return isinstance(value, str) or (isinstance(value, int)
                                      and not isinstance(value, bool))


def _initialize(msg_id: Any, params: dict[str, Any],
                app_version: str) -> dict[str, Any]:
    asked = params.get("protocolVersion")
    if not isinstance(asked, str):
        return error_response(msg_id, INVALID_PARAMS,
                              "initialize needs params.protocolVersion")
    version = asked if asked in PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return _result(msg_id, {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": app_version},
    })


def _tools_call(msg_id: Any, params: dict[str, Any],
                manager: Any) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str):
        return error_response(msg_id, INVALID_PARAMS,
                              "tools/call needs params.name")
    tool = _TOOLS.get(name)
    if tool is None:
        return error_response(msg_id, INVALID_PARAMS, f"Unknown tool: {name}")
    args = params.get("arguments", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return error_response(msg_id, INVALID_PARAMS,
                              "params.arguments must be an object")
    try:
        return _result(msg_id, tool(args, manager))
    except _ToolError as exc:
        return _result(msg_id, _tool_error(str(exc)))
    except Exception as exc:  # noqa: BLE001 - reported to the client + logged
        logger.exception("mcp: tool %s failed", name)
        return _result(msg_id, _tool_error(f"{name} failed: {exc}"))


def handle(message: Any, manager: Any, *,
           app_version: str) -> dict[str, Any] | None:
    """Answer one decoded JSON-RPC message.

    Returns the response object, or None when no response is due (a
    notification, or a response the client sent). Never raises.
    """
    try:
        return _dispatch(message, manager, app_version)
    except Exception:  # noqa: BLE001 - the transport must always answer
        logger.exception("mcp: dispatch failed")
        msg_id = message.get("id") if isinstance(message, dict) else None
        return error_response(msg_id if _valid_id(msg_id) else None,
                              INTERNAL_ERROR, "internal error")


def _dispatch(message: Any, manager: Any,
              app_version: str) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        # Includes a JSON array: 2025-06-18 removed JSON-RPC batching.
        return error_response(None, INVALID_REQUEST,
                              "expected one JSON-RPC message object")
    raw_id = message.get("id")
    msg_id = raw_id if _valid_id(raw_id) else None
    if message.get("jsonrpc") != "2.0":
        return error_response(msg_id, INVALID_REQUEST,
                              "jsonrpc must be \"2.0\"")
    if "method" not in message:
        if "id" in message and ("result" in message or "error" in message):
            return None  # a response from the client: nothing to answer
        return error_response(msg_id, INVALID_REQUEST, "method is missing")
    method = message["method"]
    if not isinstance(method, str):
        return error_response(msg_id, INVALID_REQUEST,
                              "method must be a string")
    if "id" not in message:
        # A notification: never answered, and never runs a tool.
        return None
    if msg_id is None:
        return error_response(None, INVALID_REQUEST,
                              "id must be a string or an integer")
    params = message.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return error_response(msg_id, INVALID_PARAMS,
                              "params must be an object")
    if method == "initialize":
        return _initialize(msg_id, params, app_version)
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": tool_definitions()})
    if method == "tools/call":
        return _tools_call(msg_id, params, manager)
    return error_response(msg_id, METHOD_NOT_FOUND,
                          f"Method not found: {method}")
