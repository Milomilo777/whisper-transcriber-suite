"""tools/benchmark_multilingual.py: the stdlib scorer, the normaliser and the utterance picker."""
import gzip
import importlib.util
import io
import os
import sys
import tarfile

import pytest

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools", "benchmark_multilingual.py",
)
_spec = importlib.util.spec_from_file_location("benchmark_multilingual", _PATH)
assert _spec is not None and _spec.loader is not None
bm = importlib.util.module_from_spec(_spec)
sys.modules["benchmark_multilingual"] = bm  # dataclasses looks the module up by name
_spec.loader.exec_module(bm)


# ---------------------------------------------------------------- edit distance

@pytest.mark.parametrize("a,b,expected", [
    ("kitten", "sitting", 3),
    ("", "", 0),
    ("", "abc", 3),
    ("abc", "", 3),
    ("abc", "abc", 0),
    ("flaw", "lawn", 2),
])
def test_edit_distance_known_pairs(a, b, expected):
    assert bm.edit_distance(list(a), list(b)) == expected
    assert bm.edit_distance(list(b), list(a)) == expected


def test_edit_distance_works_on_word_lists():
    assert bm.edit_distance("the cat sat".split(), "the dog sat down".split()) == 2


# --------------------------------------------------------------------- scoring

def test_wer_counts_word_errors():
    sc = bm.score("the cat sat on the mat", "the cat sat on a mat", "wer")
    assert (sc.errors, sc.ref_len) == (1, 6)
    assert sc.value == pytest.approx(1 / 6)


def test_wer_ignores_case_and_punctuation():
    assert bm.score("Hello, World!", "hello world", "wer").errors == 0


def test_wer_can_exceed_one_with_insertions():
    assert bm.score("a", "a b c d", "wer").value == pytest.approx(3.0)


def test_empty_hypothesis_is_all_deletions():
    sc = bm.score("one two three", "", "wer")
    assert sc.value == 1.0


def test_empty_reference_rules():
    assert bm.score("", "", "wer").value == 0.0
    assert bm.score("", "extra", "wer").value == 1.0
    assert bm.score("!!!", "...", "wer").value == 0.0  # only punctuation on both sides


def test_cer_ignores_spaces_for_chinese():
    sc = bm.score("\u4eca\u5929\u5929\u6c14\u5f88\u597d", "\u4eca\u5929 \u5929\u6c14 \u5f88\u597d", "cer", "zh")
    assert sc.errors == 0 and sc.ref_len == 6


def test_cer_ignores_spaces_in_the_reference_too():
    sc = bm.score("\u4eca\u5929 \u5929\u6c14", "\u4eca\u5929\u5929\u6c14", "cer", "zh")
    assert (sc.errors, sc.ref_len) == (0, 4)


def test_cer_counts_character_errors_for_japanese():
    sc = bm.score("\u4eca\u65e5\u306f\u6674\u308c\u3067\u3059", "\u4eca\u65e5\u306f\u96e8\u3067\u3059", "cer", "ja")
    # two reference characters (\u6674\u308c) become one (\u96e8): one substitution + one deletion
    assert (sc.errors, sc.ref_len) == (2, 7)


def test_cjk_wer_would_be_one_token_so_cer_is_the_metric():
    # Documents why zh/ja use CER: without spaces WER sees one big word.
    assert bm.score("\u4eca\u5929\u5929\u6c14\u5f88\u597d", "\u4eca\u5929\u5929\u6c14\u5f88\u5dee", "wer", "zh").value == 1.0
    assert bm.score("\u4eca\u5929\u5929\u6c14\u5f88\u597d", "\u4eca\u5929\u5929\u6c14\u5f88\u5dee", "cer", "zh").value == pytest.approx(1 / 6)


def test_unknown_metric_is_rejected():
    with pytest.raises(ValueError):
        bm.score("a", "a", "bleu")


# ------------------------------------------------------------------ normaliser

def test_normalize_is_nfc():
    assert bm.normalize("e\u0301") == "\u00e9"


def test_normalize_turkish_case_folding():
    assert bm.normalize("ISPARTA", "tr") == "\u0131sparta"
    assert bm.normalize("\u0130stanbul", "tr") == "istanbul"
    # Other languages use plain casefold.
    assert bm.normalize("ISPARTA", "es") == "isparta"


def test_normalize_strips_punctuation_and_symbols_incl_fullwidth():
    assert bm.normalize("Hello,  world! \u3002\u3001 ($5)") == "hello world 5"


def test_normalize_digits_of_any_script_become_ascii():
    assert bm.normalize("\u0662\u0660\u0661\u0669") == "2019"        # Arabic-Indic
    assert bm.normalize("\u06f2\u06f0\u06f1\u06f9") == "2019"        # Persian
    assert bm.normalize("\u0968\u0966\u0967\u096f") == "2019"        # Devanagari


def test_normalize_persian_zwnj_is_a_word_break():
    assert bm.normalize("\u0645\u06cc\u200c\u0631\u0648\u0645") == "\u0645\u06cc \u0631\u0648\u0645"
    assert bm.score("\u0645\u06cc\u200c\u0631\u0648\u0645", "\u0645\u06cc \u0631\u0648\u0645", "wer", "fa").errors == 0


def test_normalize_folds_arabic_yeh_kaf_and_drops_marks():
    assert bm.normalize("\u0643\u062a\u0627\u0628") == "\u06a9\u062a\u0627\u0628"
    assert bm.normalize("\u0645\u064e\u062f\u0652\u0631\u064e\u0633\u064e\u0629") == bm.normalize("\u0645\u062f\u0631\u0633\u0629")
    assert bm.normalize("\u0645\u0640\u0640\u0646") == "\u0645\u0646"


def test_normalize_keeps_devanagari_vowel_signs():
    word = "\u0939\u093f\u0928\u094d\u0926\u0940"  # contains combining signs (category Mc/Mn)
    assert bm.normalize(word) == word


# ----------------------------------------------------------------- TSV + picker

TSV = (
    "10\t111.wav\tRaw one.\tnorm one\tph\t100\tMALE\n"
    "10\t222.wav\tRaw one again.\tnorm one\tph\t100\tFEMALE\n"
    "11\t333.wav\tRaw three.\tnorm three\tph\t100\tMALE\n"
    "12\t444.wav\tRaw four.\tnorm four\tph\t100\tMALE\n"
)


def test_read_tsv_maps_file_to_sentence_and_raw_text():
    rows = bm.read_tsv(TSV)
    assert rows["111.wav"] == ("10", "Raw one.")
    assert rows["444.wav"] == ("12", "Raw four.")
    assert len(rows) == 4


def _wav(fmt_tag, rate, bytes_per_sample, n_samples, extra_chunk=False):
    fmt = (fmt_tag.to_bytes(2, "little") + (1).to_bytes(2, "little")
           + rate.to_bytes(4, "little") + (rate * bytes_per_sample).to_bytes(4, "little")
           + bytes_per_sample.to_bytes(2, "little") + (8 * bytes_per_sample).to_bytes(2, "little"))
    body = b"fmt " + len(fmt).to_bytes(4, "little") + fmt
    if extra_chunk:  # an odd-sized chunk (padded) before the data
        body += b"LIST" + (3).to_bytes(4, "little") + b"abc" + b"\x00"
    data = bytes(n_samples * bytes_per_sample)
    body += b"data" + len(data).to_bytes(4, "little") + data
    return b"RIFF" + (4 + len(body)).to_bytes(4, "little") + b"WAVE" + body


def test_wav_seconds_reads_float_and_pcm_headers():
    assert bm.wav_seconds(_wav(3, 16000, 4, 32000)) == pytest.approx(2.0)   # IEEE float (FLEURS)
    assert bm.wav_seconds(_wav(1, 16000, 2, 8000)) == pytest.approx(0.5)    # 16-bit PCM
    assert bm.wav_seconds(_wav(3, 16000, 4, 16000, extra_chunk=True)) == pytest.approx(1.0)


def test_wav_seconds_rejects_garbage():
    with pytest.raises(ValueError):
        bm.wav_seconds(b"not a wav file at all")


def _fake_tar_gz(names):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        d = tarfile.TarInfo("test")
        d.type = tarfile.DIRTYPE
        tar.addfile(d)
        for name in names:
            data = b"RIFFfake-" + name.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue())


def test_fetch_picks_first_archive_files_with_distinct_sentences(tmp_path, monkeypatch):
    archive = _fake_tar_gz([
        "test/111.wav", "test/222.wav", "test/999.wav", "test/333.wav", "test/444.wav",
    ])
    payloads = {"test.tsv": TSV.encode("utf-8"), "test.tar.gz": archive}

    def fake_get(url):
        return io.BytesIO(payloads[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(bm, "_get", fake_get)
    picked = bm.fetch_utterances("fa", 3, tmp_path)
    # 222 repeats sentence 10 and 999 is not in the TSV: both skipped.
    assert [p[0] for p in picked] == ["111", "333", "444"]
    assert picked[0][2] == "Raw one."
    assert picked[0][1].read_bytes() == b"RIFFfake-test/111.wav"
    assert picked[0][1].parent == tmp_path / "fleurs" / "fa_ir"


def test_fetch_fails_loudly_when_too_few_utterances(tmp_path, monkeypatch):
    payloads = {"test.tsv": TSV.encode("utf-8"), "test.tar.gz": _fake_tar_gz(["test/111.wav"])}
    monkeypatch.setattr(bm, "_get", lambda url: io.BytesIO(payloads[url.rsplit("/", 1)[1]]))
    with pytest.raises(RuntimeError, match="only 1 of 2"):
        bm.fetch_utterances("fa", 2, tmp_path)


def test_fetch_ignores_path_traversal_members(tmp_path, monkeypatch):
    archive = _fake_tar_gz(["test/../evil.wav", "test/111.wav"])
    payloads = {"test.tsv": TSV.encode("utf-8"), "test.tar.gz": archive}
    monkeypatch.setattr(bm, "_get", lambda url: io.BytesIO(payloads[url.rsplit("/", 1)[1]]))
    picked = bm.fetch_utterances("fa", 1, tmp_path)
    assert [p[0] for p in picked] == ["111"]
    assert not (tmp_path / "fleurs" / "evil.wav").exists()


# --------------------------------------------------------------------- summary

def test_summary_is_corpus_level_not_mean_of_utterance_rates():
    rows = [
        {"language": "es", "model": "tiny", "metric": "wer", "errors": 1, "ref_len": 2,
         "audio_s": "2.0", "decode_s": "1.0"},
        {"language": "es", "model": "tiny", "metric": "wer", "errors": 1, "ref_len": 8,
         "audio_s": "18.0", "decode_s": "5.0"},
    ]
    line = bm.summarise(rows)
    # error rate 2/10; RTF = total decode / total audio = 6/20 (a mean of rates would say 0.40)
    assert "wer 0.200 (2/10)" in line and "rtf 0.30" in line


# ------------------------------------------------- review findings (cache, invisible chars)

def test_normalize_drops_invisible_format_characters():
    assert bm.normalize("\u200b\u200bbasketbol") == "basketbol"
    assert bm.score("\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627", "\u200f\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627", "wer", "fa").errors == 0
    assert bm.normalize("\ufeffhello") == "hello"


def test_normalize_apostrophes_do_not_split_words():
    assert bm.normalize("T\u00fcrkiye'de", "tr") == "t\u00fcrkiyede"
    assert bm.normalize("T\u00fcrkiye\u2019de", "tr") == "t\u00fcrkiyede"
    assert bm.normalize("don't stop") == "dont stop"


def test_truncated_cached_wav_is_downloaded_again(tmp_path, monkeypatch):
    full = _wav(3, 16000, 4, 16000)
    tsv = TSV.encode("utf-8")

    class Archive:
        def __init__(self):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo("test/111.wav")
                info.size = len(full)
                tar.addfile(info, io.BytesIO(full))
            self.data = io.BytesIO(gzip.compress(buf.getvalue()))

    payloads = {"test.tsv": tsv, "test.tar.gz": Archive().data.getvalue()}
    monkeypatch.setattr(bm, "_get", lambda url: io.BytesIO(payloads[url.rsplit("/", 1)[1]]))
    lang_dir = tmp_path / "fleurs" / "fa_ir"
    lang_dir.mkdir(parents=True)
    (lang_dir / "111.wav").write_bytes(full[:200])  # a download that was cut off
    picked = bm.fetch_utterances("fa", 1, tmp_path)
    assert picked[0][1].read_bytes() == full
    assert not list(lang_dir.glob("*.part"))


def test_complete_cached_wav_is_kept(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(_wav(3, 16000, 4, 100))
    assert bm._wav_complete(p)
    p.write_bytes(_wav(3, 16000, 4, 100)[:-10])
    assert not bm._wav_complete(p)
    assert not bm._wav_complete(tmp_path / "missing.wav")
    p.write_bytes(b"garbage")
    assert not bm._wav_complete(p)


def test_write_atomic_leaves_no_part_file(tmp_path):
    target = tmp_path / "x.tsv"
    bm._write_atomic(target, b"abc")
    assert target.read_bytes() == b"abc" and not (tmp_path / "x.tsv.part").exists()


def test_zero_length_audio_is_an_error(tmp_path):
    p = tmp_path / "empty.wav"
    p.write_bytes(_wav(3, 16000, 4, 0))
    with pytest.raises(RuntimeError, match="no audio"):
        bm.audio_seconds(p)


def test_main_refuses_to_overwrite_an_existing_results_file(tmp_path):
    out = tmp_path / "results.csv"
    out.write_text("keep me\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="--force"):
        bm.main(["--out", str(out), "--cache", str(tmp_path / "cache")])
    assert out.read_text(encoding="utf-8") == "keep me\n"


def test_every_language_has_a_known_metric():
    for code, (folder, metric) in bm.LANGUAGES.items():
        assert metric in ("wer", "cer") and "_" in folder, code
    assert bm.LANGUAGES["zh"][1] == "cer" and bm.LANGUAGES["ja"][1] == "cer"
    assert {"fa", "zh", "es"} <= set(bm.LANGUAGES)
