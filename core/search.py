"""Search across saved transcripts (v0.8 Phase 3).

Two engines, picked at query time based on what's available:

  * **Semantic** — embed every segment with
    ``sentence-transformers/all-MiniLM-L6-v2`` (~22 MB, ONNX),
    store the vectors in a sidecar SQLite table, query via cosine
    similarity. Best result quality but the dep is heavy.
  * **FTS5** — sqlite's built-in full-text index on the segment
    text column. Works on the stock library, no extra dep, fast
    enough on ~50k segments. Worse on synonyms / paraphrase.

The :func:`search` function tries semantic first when available
and falls back to FTS5 transparently. Same return shape from
both: a list of :class:`SearchHit` (json_path + segment_index +
text + score + start_seconds).

Both engines walk the existing ``history.db`` to discover saved
transcripts; the JSON file next to each row is the source of
truth for segment text. No duplication of segment data — only
the embeddings live in their own table.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import unicodedata
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from ._gc_import_guard import gc_disabled_import
from .config import user_data_dir

logger = logging.getLogger(__name__)


SEARCH_DB_NAME = "search.db"


def search_db_path() -> Path:
    return user_data_dir() / SEARCH_DB_NAME


# ---------------------------------------------------------------- availability


def semantic_available() -> bool:
    """True iff sentence-transformers (or a minimal substitute) is importable.

    sentence-transformers pulls in torch, a heavy C-extension package --
    see core/_gc_import_guard.py for why this import (and the model load
    in Embedder._load() below) runs under a shared, process-wide
    GC-disable guard.
    """
    with gc_disabled_import():
        try:
            import sentence_transformers  # type: ignore[import-not-found] # noqa: F401
        except ImportError:
            return False
        else:
            return True


def semantic_availability_reason() -> str:
    if semantic_available():
        return ""
    return (
        "sentence-transformers not installed — `pip install "
        "sentence-transformers` to enable semantic search. Falling "
        "back to keyword search (FTS5)."
    )


# ---------------------------------------------------------------- result type


@dataclass
class SearchHit:
    json_path: str
    segment_index: int
    text: str
    score: float
    start_seconds: float = 0.0
    end_seconds: float = 0.0


# ---------------------------------------------------------------- index schema


# Bump when the table layout or the text normalisation changes: an index with
# another ``PRAGMA user_version`` is dropped once and rebuilt from the JSON files.
SCHEMA_VERSION = 2

# Characters that never help a search match: zero-width joiners (the Persian
# half-space), tatweel, soft hyphen and directional marks.
_IGNORED_CHARS = frozenset(
    "\u200c\u200d\u200e\u200f\u061c\u00ad\u0640\ufeff"
)
# Arabic letter forms folded to the Persian ones; Arabic-Indic and Persian
# digits folded to ASCII.
_FOLD_TABLE = str.maketrans({
    "\u0643": "\u06a9",  # Arabic kaf -> Persian keheh
    "\u064a": "\u06cc",  # Arabic yeh -> Persian yeh
    "\u0649": "\u06cc",  # alef maksura -> Persian yeh
    **{chr(0x0660 + i): str(i) for i in range(10)},
    **{chr(0x06F0 + i): str(i) for i in range(10)},
})


def _is_search_noise(ch: str) -> bool:
    if ch in _IGNORED_CHARS:
        return True
    if unicodedata.category(ch) != "Mn":
        return False
    code = ord(ch)
    # Latin/Greek/Cyrillic accents and Arabic vowel marks; other scripts keep
    # their combining marks (they carry meaning there).
    return (0x0300 <= code <= 0x036F or 0x064B <= code <= 0x065F
            or code == 0x0670 or 0x06D6 <= code <= 0x06ED)


def _fold(text: str, casefold: bool) -> str:
    if text.isascii():
        # NFKC, the noise list and the fold table only touch non-ASCII text.
        return text.casefold() if casefold else text
    s = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", text))
    s = "".join(ch for ch in s if not _is_search_noise(ch))
    s = unicodedata.normalize("NFC", s).translate(_FOLD_TABLE)
    if casefold:
        s = s.casefold()
    return unicodedata.normalize("NFKC", s)


def normalize_search_text(text: str) -> str:
    """Fold *text* so that spelling variants compare equal.

    Used for both the indexed text and the query, so the two always agree:
    NFKC, accents and Arabic vowel marks removed, ZWNJ/tatweel removed,
    Arabic kaf/yeh as Persian, digits as ASCII, case folded.
    """
    return _fold(text, True)


# ---- matching inside one text (transcript viewer search and Find/Replace) ----
#
# The same folding as normalize_search_text, but done one character at a time
# so every folded character knows which characters of the ORIGINAL text it
# came from. A match can then be mapped back to an exact span of the original,
# which is what Replace rewrites: folding only decides what matches, it never
# changes the text around it.


class _CharFolds(dict):  # type: ignore[type-arg]
    """``ch -> its fold``, filled on demand. ``map(table.__getitem__, text)`` folds a
    whole segment at C speed (an ``lru_cache`` call per character was the cost)."""

    def __init__(self, casefold: bool) -> None:
        super().__init__()
        self._casefold = casefold
        self.version = 0  # grows with every entry added, never resets

    def __missing__(self, ch: str) -> str:
        if len(self) > 20000:  # a stray huge text must not grow the table for good
            self.clear()
        self.version += 1
        folded = self[ch] = _fold(ch, self._casefold)
        return folded


_CHAR_FOLDS = {True: _CharFolds(True), False: _CharFolds(False)}


def _fold_char(ch: str, casefold: bool) -> str:
    return _CHAR_FOLDS[casefold][ch]


class _MarkFlags(dict):  # type: ignore[type-arg]
    """``ch -> is it a combining mark (category Mn)``, filled on demand."""

    def __missing__(self, ch: str) -> bool:
        if len(self) > 20000:
            self.clear()
        flag = self[ch] = unicodedata.category(ch) == "Mn"
        return flag


_is_mark = _MarkFlags().__getitem__


def _folded_text(text: str, casefold: bool) -> str:
    """``fold_with_spans(text)[0]`` without the spans: cheap enough for every row."""
    if text.isascii():
        return text.casefold() if casefold else text
    return _folded_non_ascii(text, casefold)


# Cached: the viewer's search box folds every segment again on each keystroke.
@lru_cache(maxsize=16384)
def _folded_non_ascii(text: str, casefold: bool) -> str:
    return "".join(map(_CHAR_FOLDS[casefold].__getitem__, text))


class _SpanIndex:
    """Where each folded character of one text came from in the original.

    Usually every kept character folds to exactly one character, so the map is
    given by the few characters that fold away (``dropped``): folded character
    ``k`` is original character ``k + (number of dropped ones before it)``, kept
    as ``adjusted`` for a bisect, and the index is small and quick to build.
    A text with an expanding character (a ligature) gets explicit ``starts`` and
    ``ends`` instead.
    """

    __slots__ = ("folded", "dropped", "adjusted", "extended", "starts", "ends")

    def __init__(self, folded: str) -> None:
        self.folded = folded
        self.dropped: tuple[int, ...] = ()
        self.adjusted: tuple[int, ...] = ()
        self.extended: dict[int, int] = {}  # folded index -> end that includes its marks
        self.starts: tuple[int, ...] | None = None
        self.ends: tuple[int, ...] | None = None

    def start_of(self, k: int) -> int:
        if self.starts is not None:
            return self.starts[k]
        return k + bisect_right(self.adjusted, k)

    def end_of(self, k: int) -> int:
        if self.ends is not None:
            return self.ends[k]
        return self.extended.get(k, self.start_of(k) + 1)

    def first_at(self, offset: int) -> int:
        """Index of the first folded character that starts at or after *offset*."""
        if self.starts is not None:
            return bisect_left(self.starts, offset)
        return max(0, offset - bisect_left(self.dropped, offset))

    def whole_chars(self, pos: int, last: int) -> bool:
        """True when folded ``pos..last`` neither starts nor ends inside one character's expansion."""
        starts = self.starts
        if starts is None:
            return True
        return (pos == 0 or starts[pos - 1] != starts[pos]) and (
            last == len(self.folded) - 1 or starts[last + 1] != starts[last]
        )


@lru_cache(maxsize=8)
def _dropped_regex(casefold: bool, version: int) -> "re.Pattern[str] | None":
    """A character class of every character seen so far that folds to nothing."""
    chars = [c for c, f in _CHAR_FOLDS[casefold].items() if not f]
    if not chars:
        return None
    return re.compile("[" + "".join(re.escape(c) for c in chars) + "]")


# Same size as _folded_non_ascii: the viewer's filter asks for the index of every
# segment on each keystroke once the query starts or ends with a half-space, and
# a smaller cache would rebuild them all every time.
@lru_cache(maxsize=16384)
def _index(text: str, casefold: bool) -> _SpanIndex:
    folded = _folded_text(text, casefold)  # also teaches the table every character
    index = _SpanIndex(folded)
    table = _CHAR_FOLDS[casefold]
    pattern = _dropped_regex(casefold, table.version)
    dropped = [m.start() for m in pattern.finditer(text)] if pattern else []
    if len(folded) == len(text) - len(dropped):
        index.dropped = tuple(dropped)
        index.adjusted = tuple(d - i for i, d in enumerate(dropped))
        extended = index.extended
        for i, d in enumerate(dropped):  # a mark that folds away stays with the letter before it
            if d and _is_mark(text[d]):
                k = d - i - 1  # the kept letter just before d, if d - 1 is kept
                if i == 0 or dropped[i - 1] != d - 1:
                    extended[k] = d + 1
                elif extended.get(k) == d:  # d - 1 was a mark that already joined it
                    extended[k] = d + 1
        return index
    starts: list[int] = []
    ends: list[int] = []
    last_len = 0  # folded characters made by the last kept original character
    for i, f in enumerate(map(table.__getitem__, text)):
        if f:
            last_len = len(f)
            starts.extend([i] * last_len)
            ends.extend([i + 1] * last_len)
        elif last_len and ends[-1] == i and _is_mark(text[i]):
            ends[-last_len:] = [i + 1] * last_len
    index.starts = tuple(starts)
    index.ends = tuple(ends)
    return index


def fold_with_spans(
    text: str, casefold: bool = True
) -> tuple[str, tuple[int, ...], tuple[int, ...]]:
    """``(folded, starts, ends)``: ``text[starts[i]:ends[i]]`` produced ``folded[i]``.

    Characters that fold to nothing (ZWNJ, tatweel, vowel marks) have no folded
    character. A combining mark that follows a kept character is attached to its
    span, so a match swallows the vowel marks of its last letter; a ZWNJ is not,
    so "ketab" matches the start of "ketab" + ZWNJ + "ha" without taking the
    half-space. ``casefold=False`` keeps Latin case (a "Match case" search).
    """
    index = _index(text, casefold)
    count = len(index.folded)
    return (
        index.folded,
        tuple(index.start_of(k) for k in range(count)),
        tuple(index.end_of(k) for k in range(count)),
    )


fold_with_spans.cache_clear = _index.cache_clear  # type: ignore[attr-defined]


def _literal_span(text: str, needle: str, start: int, casefold: bool) -> tuple[int, int] | None:
    """Plain substring search (case-insensitive when ``casefold``): no other folding."""
    start = max(0, start)
    if casefold:
        m = re.compile(re.escape(needle), re.IGNORECASE).search(text, start)
        return m.span() if m else None
    i = text.find(needle, start)
    return (i, i + len(needle)) if i >= 0 else None


@lru_cache(maxsize=256)
def _split_edges(needle: str, casefold: bool) -> tuple[str, str, str]:
    """``(prefix, core, suffix)``: the needle's leading and trailing characters that
    the folding drops, and what lies between them.

    A half-space, tatweel or vowel mark at the edge of what the user typed is
    something they mean (the "mi-" prefix, a stray tatweel to delete). Folded
    matching would drop it and widen the match, so those characters must be
    found literally next to the folded core. Inside the core they stay forgiving.
    A needle of only such characters has an empty core.
    """
    n = len(needle)
    i = 0
    while i < n and not _fold_char(needle[i], casefold):
        i += 1
    j = n
    while j > i and not _fold_char(needle[j - 1], casefold):
        j -= 1
    return needle[:i], needle[i:j], needle[j:]


def find_folded_span(
    text: str, needle: str, start: int = 0, *, casefold: bool = True, exact: bool = False
) -> tuple[int, int] | None:
    """The first match of *needle* in *text* at or after original offset *start*.

    Compares with the search folding (ZWNJ, Arabic kaf/yeh, digits, accents and,
    unless ``casefold`` is False, case). Returns the ``(start, end)`` span of the
    ORIGINAL text, or None. Matches are exact spans of the original:

    * ``exact`` turns the folding off (a plain, case-sensitive substring search);
    * a needle is tried as typed and precomposed (NFC), the leftmost hit wins, so an
      NFD paste finds precomposed text;
    * characters the folding drops (ZWNJ, tatweel, a vowel mark) at the start or
      end of the needle are matched literally, right next to the folded core; a
      needle of only such characters matches literally;
    * a match never starts or ends inside the expansion of one character
      ("f" does not match half of the ligature U+FB01).
    """
    if not needle:
        return None
    if exact:
        return _literal_span(text, needle, start, False)
    # As typed, and precomposed (an NFD paste from macOS Find): the leftmost hit wins.
    hits = [_find_spans(text, needle, start, casefold)]
    composed = unicodedata.normalize("NFC", needle)
    if composed != needle:
        hits.append(_find_spans(text, composed, start, casefold))
    return min((h for h in hits if h is not None), default=None)


def _find_spans(
    text: str, needle: str, start: int, casefold: bool
) -> tuple[int, int] | None:
    prefix, core, suffix = _split_edges(needle, casefold)
    if not core:
        return _literal_span(text, needle, start, casefold)
    wanted = _folded_text(core, casefold)
    if not wanted or wanted not in _folded_text(text, casefold):
        return None
    index = _index(text, casefold)
    folded = index.folded
    start = max(0, start)
    pos = folded.find(wanted, index.first_at(start))
    while pos >= 0:
        last = pos + len(wanted) - 1
        if index.whole_chars(pos, last):
            first_char = index.start_of(pos)
            raw_end = index.start_of(last) + 1  # the core's last letter, without its marks
            end = index.end_of(last)
            begin = first_char - len(prefix)
            if begin >= start and text.startswith(prefix, begin):
                if not suffix:
                    return begin, end
                # The suffix follows the letter's own marks (a ZWNJ after "alef + hamza")
                # or is one of them (a trailing fatha): take whichever really is there.
                for after in dict.fromkeys((end, raw_end)):
                    if text.startswith(suffix, after):
                        return begin, after + len(suffix)
        pos = folded.find(wanted, pos + 1)
    return None


def folded_contains(
    text: str, query: str, *, casefold: bool = True, exact: bool = False
) -> bool:
    """True when *query* occurs in *text* under the search folding.

    Same needle rules as :func:`find_folded_span`, except that a plain query
    (no dropped character at its edges) also counts a hit inside a character's
    expansion: a filter only has to show the row, and it runs on every segment
    at every keystroke, so it skips building spans.
    """
    if not query:
        return False
    if exact:
        return query in text
    composed = unicodedata.normalize("NFC", query)
    for variant in dict.fromkeys((query, composed)):
        prefix, _core, suffix = _split_edges(variant, casefold)
        if prefix or suffix:
            if find_folded_span(text, variant, casefold=casefold) is not None:
                return True
            continue
        wanted = _folded_text(variant, casefold)
        if wanted and wanted in _folded_text(text, casefold):
            return True
    return False


def replace_folded(
    text: str, needle: str, replacement: str, *, casefold: bool = True, exact: bool = False
) -> tuple[str, int]:
    """Replace every match of *needle* with *replacement*, literally.

    Only the matched spans of *text* change; returns ``(new_text, count)``.
    Matching follows :func:`find_folded_span`.
    """
    pieces: list[str] = []
    last = pos = count = 0
    while True:
        span = find_folded_span(text, needle, pos, casefold=casefold, exact=exact)
        if span is None:
            break
        pieces.append(text[last:span[0]])
        pieces.append(replacement)
        last = pos = span[1]
        count += 1
    if not count:
        return text, 0
    pieces.append(text[last:])
    return "".join(pieces), count


def _trigram_supported() -> bool:
    """True iff this SQLite build has the FTS5 ``trigram`` tokenizer (3.34+)."""
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(a, tokenize='trigram')")
    except sqlite3.Error:
        return False
    finally:
        probe.close()
    return True


def _schema_statements(trigram: bool) -> list[str]:
    # ``norm`` is the searchable column (normalised text); ``text`` keeps the
    # original for display. Trigram matches any substring of 3+ characters,
    # which is what unspaced scripts (Chinese, Japanese) need; queries with a
    # shorter token fall back to ``instr`` on ``norm``.
    tokenizer = "trigram" if trigram else "unicode61"
    return [
        "CREATE VIRTUAL TABLE segments_fts USING fts5("
        "json_path UNINDEXED, segment_index UNINDEXED, text UNINDEXED, norm, "
        "start_seconds UNINDEXED, end_seconds UNINDEXED, "
        f"tokenize = '{tokenizer}')",
        "CREATE TABLE embeddings ("
        "json_path TEXT NOT NULL, segment_index INTEGER NOT NULL, "
        "vector BLOB NOT NULL, dim INTEGER NOT NULL, "
        "PRIMARY KEY (json_path, segment_index))",
        "CREATE TABLE indexed_files ("
        "json_path TEXT PRIMARY KEY, mtime REAL, size INTEGER)",
    ]


def _schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _open_db(path: Path | None = None) -> sqlite3.Connection:
    p = path if path is not None else search_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if _schema_version(conn) == SCHEMA_VERSION:
        return conn
    # Fresh or old-layout index: rebuild once. The write lock is taken only
    # on this path so a normal open never waits for a running reindex, and
    # the version is re-read under the lock so two openers do not both reset.
    try:
        conn.execute("BEGIN IMMEDIATE")
        if _schema_version(conn) != SCHEMA_VERSION:
            for table in ("segments_fts", "embeddings", "indexed_files"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            for stmt in _schema_statements(_trigram_supported()):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    return conn


def _uses_trigram(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='segments_fts'"
    ).fetchone()
    return bool(row and row[0] and "trigram" in row[0])


# ---------------------------------------------------------------- indexing


def _read_segments(json_path: str) -> list[dict[str, Any]] | None:
    """Read the segment list out of a transcript JSON.

    Returns ``None`` when the file could not be READ at all (a transient
    I/O failure — locked by another process, AV scanner, network hiccup).
    ``index_file`` treats that as "skip this pass": it must not delete the
    already-indexed rows, unlike a readable file that simply holds no
    usable segments (``[]``).
    """
    try:
        # utf-8-sig: editors on Windows save transcripts with a BOM.
        with open(json_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except OSError:
        return None
    except UnicodeDecodeError:
        # Not UTF-8 (e.g. half-written or saved in another encoding): treat
        # like an unreadable file, keep the old rows and retry next pass.
        return None
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [s for s in data if isinstance(s, dict)]


def _segment_text(seg: dict[str, Any]) -> str:
    """Segment text as a stripped string; non-scalar values count as empty."""
    raw = seg.get("text")
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return ""
    return str(raw).strip()


def _finite_seconds(value: object, default: float) -> float:
    """A finite float from a possibly malformed ``start``/``end`` field.

    ``None``, text such as ``"abc"``/``"1,5"``, NaN, Infinity and integers too
    large for a float all give *default*, so one odd row neither stops the
    file from being indexed nor stores a NULL that breaks later queries.
    """
    if isinstance(value, bool):
        return default
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return out if math.isfinite(out) else default


def _file_needs_reindex(conn: sqlite3.Connection, json_path: str) -> bool:
    try:
        st = os.stat(json_path)
    except OSError:
        return False
    cur = conn.execute(
        "SELECT mtime, size FROM indexed_files WHERE json_path=?",
        (json_path,),
    )
    row = cur.fetchone()
    if row is None:
        return True
    return abs(float(row["mtime"]) - float(st.st_mtime)) > 0.5 or int(row["size"]) != int(st.st_size)


def _mark_file_indexed(conn: sqlite3.Connection, json_path: str) -> None:
    try:
        st = os.stat(json_path)
    except OSError:
        return
    conn.execute(
        "INSERT OR REPLACE INTO indexed_files (json_path, mtime, size) "
        "VALUES (?, ?, ?)",
        (json_path, float(st.st_mtime), int(st.st_size)),
    )


def _file_has_embeddings(conn: sqlite3.Connection, json_path: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM embeddings WHERE json_path=? LIMIT 1", (json_path,)
    ).fetchone()
    return row is not None


def index_file(
    json_path: str,
    *,
    conn: sqlite3.Connection | None = None,
    embedder: "Embedder | None" = None,
) -> int:
    """Reindex one transcript JSON. Returns segment count indexed.

    Idempotent: re-running on the same unchanged file is a no-op
    (size + mtime cache check). When ``embedder`` is provided, also
    writes per-segment vectors into the ``embeddings`` table; a file
    that was previously indexed without the semantic layer (dependency
    installed later) is rebuilt so those vectors get created.
    """
    owns_conn = conn is None
    conn = conn or _open_db()
    try:
        needs_reindex = _file_needs_reindex(conn, json_path)
        if not needs_reindex and embedder is not None:
            needs_reindex = not _file_has_embeddings(conn, json_path)
        if not needs_reindex:
            return 0
        segments = _read_segments(json_path)
        if segments is None:
            # Transient read failure: keep whatever is already indexed and
            # leave the file unmarked so the next pass retries it.
            logger.debug("Transcript read failed, keeping existing index: %s",
                         json_path)
            return 0
        indexed = 0
        with conn:
            conn.execute(
                "DELETE FROM segments_fts WHERE json_path=?", (json_path,)
            )
            conn.execute(
                "DELETE FROM embeddings WHERE json_path=?", (json_path,)
            )
            for idx, seg in enumerate(segments):
                text = _segment_text(seg)
                if not text:
                    continue
                start = _finite_seconds(seg.get("start"), 0.0)
                end = _finite_seconds(seg.get("end"), start)
                conn.execute(
                    "INSERT INTO segments_fts (json_path, segment_index, "
                    "text, norm, start_seconds, end_seconds) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (json_path, idx, text, normalize_search_text(text),
                     start, end),
                )
                indexed += 1
                if embedder is not None:
                    vec = embedder.embed(text)
                    conn.execute(
                        "INSERT INTO embeddings (json_path, segment_index, "
                        "vector, dim) VALUES (?, ?, ?, ?)",
                        (json_path, idx, _vector_to_blob(vec), len(vec)),
                    )
            _mark_file_indexed(conn, json_path)
        return indexed
    finally:
        if owns_conn:
            conn.close()


def reindex_all_history(
    *,
    embedder: "Embedder | None" = None,
) -> int:
    """Walk history.db, reindex every transcript JSON. Returns rows touched."""
    from .history import HistoryDB

    total = 0
    db_conn = _open_db()
    try:
        with HistoryDB() as hist:
            for row in hist.list_transcriptions(limit=10_000):
                paths = row.get("output_paths") or []
                if isinstance(paths, str):
                    try:
                        paths = json.loads(paths)
                    except json.JSONDecodeError:
                        paths = []
                for p in paths or []:
                    if isinstance(p, str) and p.lower().endswith(".json") and os.path.isfile(p):
                        try:
                            total += index_file(p, conn=db_conn, embedder=embedder)
                        except Exception as e:  # noqa: BLE001
                            # One unreadable/malformed transcript must not
                            # abort the whole walk and leave every later
                            # file unindexed.
                            logger.warning(
                                "Search index skipped %s: %s: %s",
                                p, type(e).__name__, e,
                            )
        prune_missing_files(db_conn)
    finally:
        db_conn.close()
    return total


def prune_missing_files(conn: sqlite3.Connection) -> int:
    """Drop every index row of a transcript JSON that no longer exists.

    Clears ``segments_fts``, ``embeddings`` and ``indexed_files`` so a deleted
    transcript stops being returned. Returns the number of files removed.
    """
    paths = {
        str(r[0]) for r in conn.execute(
            "SELECT json_path FROM indexed_files "
            "UNION SELECT json_path FROM embeddings "
            "UNION SELECT json_path FROM segments_fts"
        )
    }
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        with conn:
            for p in missing:
                for table in ("segments_fts", "embeddings", "indexed_files"):
                    conn.execute(f"DELETE FROM {table} WHERE json_path=?", (p,))
    return len(missing)


# ---------------------------------------------------------------- query


def search(
    query: str,
    *,
    limit: int = 20,
    embedder: "Embedder | None" = None,
    conn: sqlite3.Connection | None = None,
) -> list[SearchHit]:
    """Run the query against whichever engine is best.

    When ``embedder`` is provided we use semantic similarity over the
    pre-computed vectors. Otherwise we fall back to FTS5 keyword
    matching.
    """
    query = (query or "").strip()
    if not query:
        return []
    owns_conn = conn is None
    conn = conn or _open_db()
    try:
        if embedder is not None:
            try:
                hits = _semantic_query(conn, query, embedder, limit)
            except Exception as e:  # noqa: BLE001
                # The module contract is a transparent fallback: a semantic
                # failure (model weights missing/corrupt, encode() error)
                # must not hide the keyword index that does work.
                logger.warning(
                    "Semantic search failed (%s: %s); falling back to "
                    "keyword search",
                    type(e).__name__, e,
                )
                hits = []
            if hits:
                return hits
        return _fts_query(conn, query, limit)
    finally:
        if owns_conn:
            conn.close()


def _fts_match_query(tokens: list[str]) -> str:
    """Build an FTS5 MATCH expression from already-normalised query tokens.

    Every token is quoted, so FTS5 operators the user may have typed (``:``,
    ``*``, ``OR``, ``NEAR`` ...) are treated as literal text instead of
    changing the query or raising ``sqlite3.OperationalError``. Joining quoted
    tokens with a space is FTS5's implicit AND: typing "cat dog" finds
    segments containing BOTH words, not only the exact phrase "cat dog".
    """
    return " ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def _fts_query(conn: sqlite3.Connection, query: str, limit: int) -> list[SearchHit]:
    tokens = normalize_search_text(query).split()
    if not tokens:
        return []
    trigram = _uses_trigram(conn)
    # The trigram index answers substring queries of 3+ characters; shorter
    # tokens (a two-character Chinese word) and a build without trigram use a
    # plain substring scan of the normalised text instead.
    indexed = [t for t in tokens if trigram and len(t) >= 3]
    scanned = [t for t in tokens if not (trigram and len(t) >= 3)]
    where: list[str] = []
    params: list[Any] = []
    if indexed:
        where.append("segments_fts MATCH ?")
        params.append(_fts_match_query(indexed))
    for t in scanned:
        where.append("instr(norm, ?) > 0")
        params.append(t)
    # COALESCE: rows written by an older build may hold NULL timestamps.
    select = (
        "SELECT json_path, segment_index, text, length(norm) AS nlen, "
        "COALESCE(start_seconds, 0.0) AS start_seconds, "
        "COALESCE(end_seconds, 0.0) AS end_seconds"
    )
    if indexed:
        sql = (f"{select}, bm25(segments_fts) AS rank FROM segments_fts "
               f"WHERE {' AND '.join(where)} ORDER BY rank LIMIT ?")
    else:
        sql = (f"{select} FROM segments_fts WHERE {' AND '.join(where)} "
               "ORDER BY nlen, json_path, segment_index LIMIT ?")
    rows = conn.execute(sql, (*params, limit)).fetchall()
    qlen = sum(len(t) for t in tokens)
    out: list[SearchHit] = []
    for r in rows:
        if indexed:
            # bm25 is smaller-is-better and (in FTS5) NEGATIVE, so the old
            # ``max(0.0, rank)`` clamped every hit to exactly 1.0. The
            # logistic map is strictly decreasing for either sign and stays
            # inside (0, 1); the clamp only guards math.exp overflow.
            score = 1.0 / (1.0 + math.exp(min(float(r["rank"]), 500.0)))
        else:
            # No bm25 without MATCH: score by how much of the segment the
            # query covers (shorter segment = tighter match).
            score = qlen / (qlen + int(r["nlen"]))
        out.append(SearchHit(
            json_path=str(r["json_path"]),
            segment_index=int(r["segment_index"]),
            text=str(r["text"]),
            score=score,
            start_seconds=_finite_seconds(r["start_seconds"], 0.0),
            end_seconds=_finite_seconds(r["end_seconds"], 0.0),
        ))
    return out


def _semantic_query(
    conn: sqlite3.Connection,
    query: str,
    embedder: "Embedder",
    limit: int,
) -> list[SearchHit]:
    qvec = embedder.embed(query)
    qnorm = math.sqrt(sum(x * x for x in qvec)) or 1.0
    cur = conn.execute(
        "SELECT e.json_path, e.segment_index, e.vector, e.dim, s.text, "
        "COALESCE(s.start_seconds, 0.0) AS start_seconds, "
        "COALESCE(s.end_seconds, 0.0) AS end_seconds FROM embeddings e "
        "JOIN segments_fts s ON e.json_path = s.json_path "
        "AND e.segment_index = s.segment_index"
    )
    hits: list[SearchHit] = []
    for r in cur.fetchall():
        vec = _blob_to_vector(bytes(r["vector"]), int(r["dim"]))
        if not vec:
            continue
        if len(vec) != len(qvec):
            # A stored embedding from a different model/dimension than the
            # one embedding this query (e.g. the embedding model changed
            # since this row was indexed) is incompatible, not just noisy —
            # zip() would silently truncate to the shorter vector and score
            # it against a meaningless partial dot product. Skip it; a
            # reindex is what actually fixes this row, not a bogus score.
            continue
        vnorm = math.sqrt(sum(x * x for x in vec)) or 1.0
        dot = sum(a * b for a, b in zip(qvec, vec))
        score = dot / (qnorm * vnorm)
        hits.append(SearchHit(
            json_path=str(r["json_path"]),
            segment_index=int(r["segment_index"]),
            text=str(r["text"]),
            score=float(score),
            start_seconds=_finite_seconds(r["start_seconds"], 0.0),
            end_seconds=_finite_seconds(r["end_seconds"], 0.0),
        ))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


# ---------------------------------------------------------------- embedder


class Embedder:
    """Wraps a sentence-transformers model.

    Construct with ``Embedder(model_name="all-MiniLM-L6-v2")`` —
    the first :meth:`embed` call loads the model lazily so import-
    time stays cheap.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        if not semantic_available():
            raise RuntimeError(semantic_availability_reason())
        with gc_disabled_import():
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
            self._model = SentenceTransformer(self.model_name)

    def embed(self, text: str) -> list[float]:
        self._load()
        assert self._model is not None
        vec = self._model.encode(text, normalize_embeddings=False)
        return [float(x) for x in (vec.tolist() if hasattr(vec, "tolist") else vec)]


# ---------------------------------------------------------------- BLOB pack


def _vector_to_blob(vec: Iterable[float]) -> bytes:
    """Pack a float list into a compact little-endian float32 blob."""
    import struct
    return b"".join(struct.pack("<f", float(x)) for x in vec)


def _blob_to_vector(blob: bytes, dim: int) -> list[float]:
    import struct
    if len(blob) < dim * 4:
        return []
    return list(struct.unpack(f"<{dim}f", blob[: dim * 4]))
