"""The first-download prompt names the selected model's real size.

It used to say "about 3 GB" for every model, including the ~0.5 GB Small
(open issue #5 in docs/MACOS_BUILD_NOTES.md).
"""
from __future__ import annotations

import pytest

from core import model_manager as mm


@pytest.mark.parametrize(
    "slug, expected",
    [
        ("tiny", "about 80 MB"),
        ("small", "about 500 MB"),
        ("medium", "about 1.5 GB"),
        ("large-v3", "about 3 GB"),
    ],
)
def test_size_text_follows_the_catalog(slug, expected):
    assert slug in mm.MODEL_REGISTRY
    assert mm.approx_download_size_text({}, slug) == expected


def test_unknown_model_gives_no_size_instead_of_a_guess():
    assert mm.approx_download_size_text({}, "no-such-model") == ""
