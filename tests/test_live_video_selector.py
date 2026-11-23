"""Behavioural tests for the Gemini Live frame selector (no Qt, no display needed)."""
from kira.live_video_selector import (
    SAMPLE_CELLS,
    LiveFrameSelector,
    SelectorPolicy,
    measure_change,
)


def flat(value=100, cells=SAMPLE_CELLS):
    return bytes([value]) * cells


def with_patch(base, count, value):
    """Return a copy of ``base`` where the first ``count`` cells are set to ``value``."""
    data = bytearray(base)
    for index in range(count):
        data[index] = value
    return bytes(data)


def test_first_frame_is_always_sent():
    selector = LiveFrameSelector()
    decision = selector.evaluate(flat())
    assert decision.send and decision.reason == "first"


def test_identical_frame_is_skipped_after_commit():
    selector = LiveFrameSelector()
    frame = flat()
    selector.commit(frame)
    decision = selector.evaluate(frame)
    assert not decision.send and decision.reason == "unchanged"
    assert selector.skipped_unchanged == 1


def test_large_global_change_is_sent():
    selector = LiveFrameSelector()
    selector.commit(flat(100))
    decision = selector.evaluate(flat(130))  # ~11.8% mean change
    assert decision.send and decision.reason == "mean_change"


def test_small_popup_is_sent_even_though_the_mean_barely_moves():
    selector = LiveFrameSelector()
    base = flat(100)
    selector.commit(base)
    popup = with_patch(base, 30, 240)  # 30 of 2304 cells, mean change ~1.8% of cells * 55%
    decision = selector.evaluate(popup)
    mean, strong = measure_change(base, popup, selector.policy.cell_threshold)
    assert mean < selector.policy.mean_threshold
    assert strong >= selector.policy.hotspot_cells
    assert decision.send and decision.reason == "local_change"


def test_cursor_sized_change_is_ignored():
    selector = LiveFrameSelector()
    base = flat(100)
    selector.commit(base)
    decision = selector.evaluate(with_patch(base, 2, 255))
    assert not decision.send and decision.reason == "unchanged"


def test_faint_noise_across_the_frame_is_ignored():
    selector = LiveFrameSelector()
    base = flat(100)
    selector.commit(base)
    decision = selector.evaluate(flat(103))  # 1.2% per cell, below both thresholds
    assert not decision.send


def test_reference_changes_only_on_commit_so_a_rejected_frame_is_retried():
    selector = LiveFrameSelector()
    selector.commit(flat(100))
    changed = flat(160)
    assert selector.evaluate(changed).send
    # The frame was not queued (rate limit / encode error): no commit, so the next tick retries.
    assert selector.evaluate(changed).send
    selector.commit(changed)
    assert not selector.evaluate(changed).send


def test_slow_drift_accumulates_against_the_last_sent_frame():
    selector = LiveFrameSelector(SelectorPolicy(mean_threshold=0.015))
    selector.commit(flat(100))
    sent = False
    for step in range(1, 12):  # +1 level per tick: ~0.4% per tick, ~4.3% in total
        if selector.evaluate(flat(100 + step)).send:
            sent = True
            break
    assert sent


def test_reset_makes_the_next_frame_send_again():
    selector = LiveFrameSelector()
    frame = flat()
    selector.commit(frame)
    assert not selector.evaluate(frame).send
    selector.reset()
    decision = selector.evaluate(frame)
    assert decision.send and decision.reason == "first"


def test_size_change_is_sent_and_empty_sample_is_skipped():
    selector = LiveFrameSelector()
    selector.commit(flat(cells=SAMPLE_CELLS))
    assert selector.evaluate(flat(cells=SAMPLE_CELLS // 2)).reason == "size_changed"
    assert not selector.evaluate(b"").send


def test_snapshot_counts_decisions():
    selector = LiveFrameSelector()
    frame = flat()
    selector.evaluate(frame)
    selector.commit(frame)
    selector.evaluate(frame)
    assert selector.snapshot() == {"evaluated": 2, "sent": 1, "skipped_unchanged": 1}
