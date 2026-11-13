"""Keep the original/translation pair distinct while merging short cues."""
import pytest
from core.writers import bilingual_srt


@pytest.mark.parametrize('originals,translations,expected', [
    (['A B','A'],['C','B C'],'A B C A B C'),
    (['a --> b','a → b'],['T','T'],'a → b T a → b T'),
],ids=['language-boundary','cue-separator'])
def test_distinct_source_pairs_survive_cue_merging(originals,translations,expected):
    segments=[{'start':0,'end':0,'text':originals[0]},
              {'start':0,'end':1,'text':originals[1]}]
    body=bilingual_srt.write(segments,translations)
    assert ' '.join(body.splitlines()[2:]).strip()==expected


def test_exact_source_pair_is_still_deduplicated():
    body=bilingual_srt.write([{'start':0,'end':0,'text':'Original'},
                             {'start':0,'end':1,'text':'Original'}],['Translation','Translation'])
    assert ' '.join(body.splitlines()[2:]).strip()=='Original Translation'
