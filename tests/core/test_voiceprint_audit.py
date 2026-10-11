import pytest
from core.voiceprint import (
    _open_db, enrol_with_vector, list_voices, cosine, match_vector, relabel_segments, EnrolledVoice
)

class TestVoiceprint:
    def test_cosine(self):
        assert cosine([1, 0], [1, 0]) == 1.0
        assert cosine([1, 0], [0, 1]) == 0.0
        assert cosine([1, 0], [-1, 0]) == -1.0
        assert cosine([], []) == 0.0
        assert cosine([1], [1, 1]) == 0.0

    def test_enrol_with_vector(self, tmp_path):
        db_path = tmp_path / "voices.db"
        conn = _open_db(db_path)
        with pytest.raises(ValueError, match="non-empty"):
            enrol_with_vector("", [1.0], conn=conn)
        
        with pytest.raises(ValueError, match="non-empty"):
            enrol_with_vector("Alice", [], conn=conn)
            
        with pytest.raises(ValueError, match="finite values"):
            enrol_with_vector("Alice", [float('nan')], conn=conn)
            
        vid = enrol_with_vector("Alice", [1.0, 0.0], conn=conn)
        assert vid > 0
        
        voices = list_voices(conn=conn)
        assert len(voices) == 1
        assert voices[0].name == "Alice"
        assert voices[0].vector == [1.0, 0.0]
        conn.close()

    def test_match_vector(self):
        voices = [
            EnrolledVoice(1, "Alice", [1.0, 0.0, 0.0]),
            EnrolledVoice(2, "Bob", [0.0, 1.0, 0.0])
        ]
        
        match = match_vector([1.0, 0.0, 0.0], voices=voices, threshold=0.9)
        assert match is not None
        assert match.name == "Alice"
        
        match = match_vector([0.0, 1.0, 0.0], voices=voices, threshold=0.9)
        assert match is not None
        assert match.name == "Bob"
        
        match = match_vector([0.0, 0.0, 1.0], voices=voices, threshold=0.9)
        assert match is None
        
        # Test dim mismatch
        match = match_vector([1.0, 0.0], voices=voices, threshold=0.1)
        assert match is None

    def test_relabel_segments(self):
        voices = [EnrolledVoice(1, "Alice", [1.0, 0.0]), EnrolledVoice(2, "Bob", [0.0, 1.0])]
        
        segs = [
            {"speaker": "SPEAKER_00", "text": "hello"},
            {"speaker": "SPEAKER_01", "text": "world"},
            {"speaker": "SPEAKER_02", "text": "missing"},
            {"speaker": "Alice", "text": "already set"}
        ]
        
        vectors = {
            "SPEAKER_00": [1.0, 0.0],
            "SPEAKER_01": [0.0, 1.0],
            "SPEAKER_02": [-1.0, -1.0], # no match
        }
        
        changed = relabel_segments(segs, cluster_vectors=vectors, voices=voices)
        assert changed == 2
        assert segs[0]["speaker"] == "Alice"
        assert segs[1]["speaker"] == "Bob"
        assert segs[2]["speaker"] == "SPEAKER_02"
        assert segs[3]["speaker"] == "Alice"

    def test_match_vector_dim_mismatch(self):
        voices = [EnrolledVoice(1, "Alice", [1.0, 0.0])]
        # dimension mismatch (query is length 3, voice is length 2)
        match = match_vector([1.0, 0.0, 0.0], voices=voices, threshold=0.1)
        assert match is None
