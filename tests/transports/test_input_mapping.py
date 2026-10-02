import pytest

from callbot.transports.input_mapping import caller_input_from_transcript


def test_mapping_preserves_transcript_and_metadata():
    caller = caller_input_from_transcript(
        3, "  Nguyễn Văn A.  ", audio_url="https://clip", confidence=0.1
    )
    assert caller.turn == 3 and caller.text == "  Nguyễn Văn A.  "
    assert caller.audio_url == "https://clip" and caller.asr_confidence == 0.1
    assert not caller.is_silence and caller.phone_status is None


@pytest.mark.parametrize("text", [None, "", "vâng"])
def test_explicit_silence_discards_transcript_and_confidence(text):
    caller = caller_input_from_transcript(
        2, text, silence_ms=2000, audio_url="https://clip", confidence=1
    )
    assert caller.text is None and caller.asr_confidence is None
    assert caller.is_silence and caller.audio_url == "https://clip"
