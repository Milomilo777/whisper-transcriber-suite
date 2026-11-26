from __future__ import annotations

import pytest

from tools.release_badges_rewrite import rewrite


REPO = "Milomilo777/whisper-transcriber-suite"
SHIELDS = f"https://img.shields.io/github/downloads/{REPO}/"
LEGACY_RAW = f"https://raw.githubusercontent.com/{REPO}/badges/"
RAW = f"https://raw.githubusercontent.com/{REPO}/master/docs/badges/"


def test_legacy_and_shields_images_move_to_master():
    legacy = LEGACY_RAW + "v2.5.0-this-version.svg"
    shields = SHIELDS + "total?label=downloads"
    body = f"[![بارگیری](<{legacy}> 'Title')](https://example.org)\r\n<img src='{shields}'>"
    expected = body.replace(legacy, RAW + "v2.5.0-this-version.svg").replace(shields, RAW + "total.svg")
    assert rewrite(body) == expected
    assert rewrite(expected) == expected


def test_legacy_html_and_escaped_tag_are_rewritten():
    url = LEGACY_RAW + "v2.5.0%2Bbuild-grey.svg"
    body = f"<IMG alt='downloads' SRC={url}>"
    assert rewrite(body) == body.replace(LEGACY_RAW, RAW)


def test_legacy_image_keeps_query_and_fragment():
    url = LEGACY_RAW + "total.svg?raw=1#badge"
    body = f"![downloads]({url})\n<img src='{url}'>"
    assert rewrite(body) == body.replace(LEGACY_RAW, RAW)


def test_legacy_non_images_and_other_paths_are_preserved():
    url = LEGACY_RAW + "total.svg"
    body = (f"[ordinary link]({url})\n`![example]({url})`\n<!-- <img src='{url}'> -->\n"
            f"![nested]({LEGACY_RAW}subdir/total.svg)\n![foreign]({url.replace(REPO, 'example/other')})")
    assert rewrite(body) == body


@pytest.mark.parametrize(("suffix", "filename"), [
    ("total?label=downloads&color=207a80", "total.svg"),
    ("total?label=all%20versions&color=207a80", "total-all-versions.svg"),
    ("v2.4.0/total?label=this%20version&color=207a80", "v2.4.0-this-version.svg"),
    ("v2.3.1/total?color=207a80&label=v2.3.1", "v2.3.1.svg"),
    ("v2.0.0/total?label=v2.0.0&color=8a8a8a", "v2.0.0-grey.svg"),
])
def test_image_url_only(suffix, filename):
    body = '[![Donwloads](<{}> "Title")](https://example.org)\r\nΔ\r\n'
    assert rewrite(body.format(SHIELDS + suffix)) == body.format(RAW + filename)


def test_html_and_unrelated_text():
    old = SHIELDS + "v2.4.0/total?label=this%20version&amp;color=207a80"
    body = f'<img alt="Download" src="{old}" width="100">'
    assert rewrite(body) == f'<img alt="Download" src="{RAW}v2.4.0-this-version.svg" width="100">'
    unrelated = f"[plain link]({old})\n![stars](https://img.shields.io/github/stars/{REPO})\n{old}"
    assert rewrite(unrelated) == unrelated


def test_invalid_foreign_image_url_does_not_block_rewrite():
    other = '<img src="https://[unclosed">\n'
    body = f"{other}![downloads]({SHIELDS}total)"
    assert rewrite(body) == f"{other}![downloads]({RAW}total.svg)"


def test_multiple_badges_idempotent_and_exact_line_endings():
    one = SHIELDS + "total?label=downloads&color=207a80"
    two = SHIELDS + "v2.4.0/total?label=this%20version&color=207a80"
    body = f"## 新着\r\n[![downloads]({one})](https://example.org) ![version]({two})"
    expected = body.replace(one, RAW + "total.svg").replace(two, RAW + "v2.4.0-this-version.svg")
    assert rewrite(body) == expected
    assert rewrite(expected) == expected


def test_verbatim_examples_and_html_attributes_are_preserved():
    url = SHIELDS + "total?label=downloads&color=207a80"
    image = f"![downloads]({url})"
    sample = f"`{image}`\n\n~~~markdown\n{image}\n~~~\n<!-- {image} -->\n"
    unrelated = f"<img alt='an example: src=\"{url}\"' src='example.png'>\n"
    assert rewrite(sample + unrelated + image) == sample + unrelated + f"![downloads]({RAW}total.svg)"


def test_indented_example_and_mixed_fence_delimiters_are_preserved():
    image = f"![downloads]({SHIELDS}total)"
    sample = f"    {image}\n\n```text\n```~\n{image}\n````\n\n"
    assert rewrite(sample + image) == sample + f"![downloads]({RAW}total.svg)"


def test_backticks_inside_image_alt_text_do_not_split_the_image():
    old = SHIELDS + "total"
    body = f'![`downloads`]({old})\n<img alt="`downloads`" src="{old}">'
    assert rewrite(body) == body.replace(old, RAW + "total.svg")


@pytest.mark.parametrize("prefix", ["Downloads\n", "- Downloads\n\n", "1. Downloads\n\n"])
def test_indented_paragraph_and_list_images_are_rewritten(prefix):
    body = f"{prefix}    ![downloads]({SHIELDS}total)\n"
    assert rewrite(body) == f"{prefix}    ![downloads]({RAW}total.svg)\n"


@pytest.mark.parametrize("prefix", ["# Downloads\n    ", "- Downloads\n\n      "])
def test_indented_code_after_heading_or_inside_list_is_preserved(prefix):
    body = f"{prefix}![downloads]({SHIELDS}total)\n"
    assert rewrite(body) == body
