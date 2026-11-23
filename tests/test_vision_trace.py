"""vision_trace writes scalar-only Game Mode diagnostics to DATA_DIR/logs/vision_trace.jsonl."""
import json

from kira import config, request_trace


def _records(tmp_path):
    path = tmp_path / "logs" / "vision_trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_vision_trace_writes_a_jsonl_record(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    request_trace.vision_trace("turn_context", status="no_game_window", images_in_turn=0)
    records = _records(tmp_path)
    assert len(records) == 1
    assert records[0]["phase"] == "turn_context"
    assert records[0]["status"] == "no_game_window"
    assert records[0]["images_in_turn"] == 0


def test_vision_trace_drops_non_scalar_payloads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    request_trace.vision_trace("attach_ok", jpeg_bytes=1234, pixels=b"\xff\xd8", frames=[1, 2])
    record = _records(tmp_path)[0]
    assert record["jpeg_bytes"] == 1234
    assert "pixels" not in record
    assert "frames" not in record


def test_vision_trace_does_not_touch_the_request_trace_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    request_trace.vision_trace("command", action="enable")
    assert not (tmp_path / "logs" / "request_trace.jsonl").exists()
