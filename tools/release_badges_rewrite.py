"""Rewrite the project's inline Shields download images in GitHub release Markdown."""
from __future__ import annotations

from html import unescape
import re
import sys
from urllib.parse import parse_qs, quote, unquote, urlsplit


REPOSITORY = "Milomilo777/whisper-transcriber-suite"
SHIELDS_PATH = f"/github/downloads/{REPOSITORY}/"
SHIELDS_URL = f"https://img.shields.io{SHIELDS_PATH}"
RAW = f"https://raw.githubusercontent.com/{REPOSITORY}/badges/"
ATTRIBUTE = re.compile(r'''([^\s/="'<>]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s<>]+))?''')
LIST_ITEM = re.compile(r"^ {0,3}(?:[-+*]|[0-9]{1,9}[.)])[ \t]+")
BLOCK_BOUNDARY = re.compile(r"^ {0,3}(?:#{1,6}(?:[ \t]|$)|`{3,}|~{3,}|[<>]|(?:=+|-+)[ \t]*$)")
TOKENS = re.compile(
    r"^ {0,3}(?P<backticks>`{3,})[^`\r\n]*\r?\n.*?"
    r"(?:^ {0,3}(?P=backticks)`*[ \t]*(?=\r?$)|\Z)"
    r"|^ {0,3}(?P<tildes>~{3,})[^\r\n]*\r?\n.*?"
    r"(?:^ {0,3}(?P=tildes)~*[ \t]*(?=\r?$)|\Z)"
    r"|^(?P<indent>[ \t]*(?: {4}|\t)[ \t]*)(?P<indented>[^\r\n]*)"
    r"|<!--.*?(?:-->|\Z)"
    r"|(?<!`)(?P<ticks>`+)(?!`).*?(?<!`)(?P=ticks)(?!`)"
    r"|(?P<md>(?<!\\)(?:\\\\)*!\[(?:\\[^\r\n]|[^\]\\\r\n])*\]\([ \t]*<?)"
    r"(?P<url>https://img\.shields\.io/[^\s<>)]+)(?=[>\s)])"
    r'''|(?P<html><img(?=[\s/>])(?:"[^"]*"|'[^']*'|[^'">])*>)''',
    re.M | re.S | re.I,
)


def badge_url(url: str) -> str:
    if not url.lower().startswith(SHIELDS_URL.lower()):
        return url
    parts = urlsplit(unescape(url))
    path = parts.path[len(SHIELDS_PATH):]
    options = parse_qs(parts.query)
    label = options.get("label", [""])[0]
    if path == "total":
        filename = "total-all-versions" if label == "all versions" else "total"
    else:
        tag, separator, stat = path.partition("/")
        tag = unquote(tag)
        if not separator or stat != "total" or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._+-]*", tag):
            return url
        if label == "this version":
            tag += "-this-version"
        elif options.get("color", [""])[0].lower() == "8a8a8a":
            tag += "-grey"
        filename = quote(tag)
    return f"{RAW}{filename}.svg"


def is_indented_content(match: re.Match[str]) -> bool:
    # Indentation can continue a paragraph or be relative to a list marker.
    indentation = len(match["indent"].expandtabs(4))
    after_blank = False
    for line in reversed(match.string[:match.start()].splitlines()):
        if not line.strip():
            after_blank = True
            continue
        item = LIST_ITEM.match(line)
        if item:
            return 0 <= indentation - len(item[0].expandtabs(4)) < 4
        if not line.expandtabs(4).startswith("    "):
            return not after_blank and not BLOCK_BOUNDARY.match(line)
    return False


def rewrite_token(match: re.Match[str]) -> str:
    if match["md"] is not None:
        return match["md"] + badge_url(match["url"])
    if match["indent"] is not None and is_indented_content(match):
        return match["indent"] + TOKENS.sub(rewrite_token, match["indented"])
    tag = match[0]
    if match["html"] is None:
        return tag
    for attr in ATTRIBUTE.finditer(tag, len("<img"), len(tag) - 1):
        if attr[1].lower() != "src" or attr[2] is None:
            continue
        start, end = attr.span(2)
        if tag[start] in "\"'":
            start += 1
            end -= 1
        return tag[:start] + badge_url(tag[start:end]) + tag[end:]
    return tag


def rewrite(body: str) -> str:
    return TOKENS.sub(rewrite_token, body)


if __name__ == "__main__":
    sys.stdout.buffer.write(rewrite(sys.stdin.buffer.read().decode("utf-8")).encode("utf-8"))
