import sys
import types
import wave

import pytest

from kira import voice


def _wav(path, ms=100, value=10000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(1000)
        w.writeframes(b"".join(int(value).to_bytes(2, "little", signed=True) for _ in range(ms)))


def test_native_player_scales_volume_and_purges(tmp_path, monkeypatch):
    calls = []
    fake = types.SimpleNamespace(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4, SND_PURGE=8,
                                 PlaySound=lambda *a: calls.append(a))
    monkeypatch.setitem(sys.modules, "winsound", fake)
    src = tmp_path / "a.wav"
    _wav(src)
    pl = voice._NativeWavPlayer(str(src), 0.5)
    assert pl.duration_ms == 100
    played = calls[0][0]
    assert played.endswith(".vol.wav")
    with wave.open(played) as w:
        assert int.from_bytes(w.readframes(1), "little", signed=True) == 5000
    pl.stop()
    assert calls[-1][0] is None


def test_native_player_full_volume_plays_original(tmp_path, monkeypatch):
    calls = []
    fake = types.SimpleNamespace(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4, SND_PURGE=8,
                                 PlaySound=lambda *a: calls.append(a))
    monkeypatch.setitem(sys.modules, "winsound", fake)
    src = tmp_path / "a.wav"
    _wav(src)
    voice._NativeWavPlayer(str(src), 1.0)
    assert calls[0][0] == str(src)
