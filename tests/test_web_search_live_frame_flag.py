"""The live Game Mode frame provenance flag must survive web/image-search payload rebuilds."""
from kira.app.web_search import WebSearchApplicationService

merge = WebSearchApplicationService.merge_search_content

FRAME = {"name": "game-screen.jpg", "kind": "image"}


def _structured(flag):
    base = {"text": "what is the best move?", "files": [], "images": [FRAME]}
    if flag is not None:
        base["live_game_frame_attached"] = flag
    return base


def _legacy(flag):
    base = {
        "display": "d", "stored": "s", "model": "what is the best move?",
        "images": [{"mime": "image/jpeg", "b64": "AAAA", "name": "game-screen.jpg"}],
    }
    if flag is not None:
        base["live_game_frame_attached"] = flag
    return base


def test_flag_survives_structured_merge():
    out = merge(_structured(True), [FRAME], "evidence")
    assert out["live_game_frame_attached"] is True
    assert out["images"] == [FRAME]


def test_flag_not_invented_when_absent_or_false():
    assert "live_game_frame_attached" not in merge(_structured(None), [FRAME], "evidence")
    assert "live_game_frame_attached" not in merge(_structured(False), [FRAME], "evidence")


def test_flag_dropped_when_no_image_remains():
    out = merge(_structured(True), [], "evidence")
    assert "live_game_frame_attached" not in out


def test_plain_text_base_has_no_flag():
    out = merge("just text", [], "evidence")
    assert "live_game_frame_attached" not in out


def test_legacy_payload_keeps_model_text_and_does_not_stringify_the_dict():
    base = _legacy(True)
    out = merge(base, base["images"], "evidence")
    assert out["model"] == "what is the best move?\n\nevidence"
    assert "b64" not in out["model"]
    assert out["live_game_frame_attached"] is True
    assert out["images"] == base["images"]


def test_legacy_payload_flag_dropped_when_no_image_remains():
    out = merge(_legacy(True), [], "evidence")
    assert "live_game_frame_attached" not in out
    assert out["model"].endswith("evidence")
