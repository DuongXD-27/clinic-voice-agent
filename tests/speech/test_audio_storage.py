import os
import time

import pytest

from speech.audio.storage import AudioArtifactStore
from speech.types import NARROWBAND_RATE, AudioSegment


def _segment() -> AudioSegment:
    return AudioSegment(pcm=b"\x00\x00" * 80, sample_rate=NARROWBAND_RATE)


def _age(path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


def test_purge_removes_only_stale_call_dirs(tmp_path) -> None:
    store = AudioArtifactStore(str(tmp_path), "http://bot")
    store.save("call_old", 1, _segment())
    store.save("call_new", 1, _segment())
    demo_old = tmp_path / "demo-input" / "call_old"
    demo_new = tmp_path / "demo-input" / "call_new"
    demo_old.mkdir(parents=True)
    demo_new.mkdir(parents=True)
    (demo_old / "1.wav").write_bytes(b"x")
    (demo_new / "1.wav").write_bytes(b"x")
    _age(tmp_path / "call_old", 3600)
    _age(demo_old, 3600)

    removed = store.purge_older_than(600)

    assert removed == 2
    assert not (tmp_path / "call_old").exists()
    assert not demo_old.exists()
    assert (tmp_path / "call_new" / "1.wav").exists()
    assert (demo_new / "1.wav").exists()
    # Thư mục gốc demo-input không bị coi là một cuộc gọi, kể cả khi đã cũ.
    assert (tmp_path / "demo-input").is_dir()


def test_purge_missing_directory_is_noop(tmp_path) -> None:
    store = AudioArtifactStore(str(tmp_path / "absent"), "http://bot")

    assert store.purge_older_than(600) == 0


def test_cached_audio_requires_matching_utterance_and_ready_file(tmp_path):
    store = AudioArtifactStore(str(tmp_path), "http://bot")
    assert store.cached_url("c_cache", 1, "đã duyệt") is None
    url = store.save("c_cache", 1, _segment())
    assert store.cached_url("c_cache", 1, "đã duyệt") is None
    store.remember_utterance("c_cache", 1, "đã duyệt")
    assert store.cached_url("c_cache", 1, "đã duyệt") == url
    assert store.cached_url("c_cache", 1, "câu khác") is None
    store.path_for("c_cache", 1).unlink()
    assert store.cached_url("c_cache", 1, "đã duyệt") is None


def test_failed_atomic_replace_keeps_previous_wav_and_removes_temp_file(tmp_path, monkeypatch):
    store = AudioArtifactStore(str(tmp_path), "http://bot")
    store.save("c_atomic", 1, _segment())
    path = store.path_for("c_atomic", 1)
    before = path.read_bytes()

    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save("c_atomic", 1, AudioSegment(pcm=b"\x01\x00" * 160, sample_rate=8000))
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]
