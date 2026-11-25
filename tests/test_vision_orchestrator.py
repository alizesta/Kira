"""Regression tests for centralized Vision frame routing and backpressure."""
import threading
import unittest

from kira.vision_orchestrator import FrameContext, FrameJob, VisionFrameOrchestrator


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class VisionOrchestratorTests(unittest.TestCase):
    def test_each_frame_gets_exactly_one_route_even_when_live_and_analysis_compete(self):
        orchestrator = VisionFrameOrchestrator()
        context = orchestrator.create_context("session-a", "desktop", {"hwnd": 4})
        first = orchestrator.decide(context, live_ready=True, analysis_allowed=True)
        second = orchestrator.decide(context, live_ready=False, analysis_allowed=True)
        self.assertEqual(first.route, orchestrator.LIVE)
        self.assertEqual(second, first)
        self.assertEqual(orchestrator.snapshot()["duplicate_frames"], 1)

    def test_latest_pending_frame_replaces_oldest_when_capture_outpaces_processing(self):
        orchestrator = VisionFrameOrchestrator(capacity=1)
        first = orchestrator.create_context("s", "desktop")
        second = orchestrator.create_context("s", "desktop")
        self.assertTrue(orchestrator.enqueue(FrameJob(first, b"old")))
        self.assertTrue(orchestrator.enqueue(FrameJob(second, b"new")))
        self.assertEqual(orchestrator.take_next().context.frame_id, second.frame_id)
        self.assertEqual(orchestrator.snapshot()["dropped_pending"], 1)

    def test_cancelled_session_cannot_enqueue_or_dispatch_stale_frames(self):
        orchestrator = VisionFrameOrchestrator()
        context = orchestrator.create_context("session-a", "desktop")
        orchestrator.enqueue(FrameJob(context, b"frame"))
        orchestrator.cancel_session("session-a")
        self.assertIsNone(orchestrator.take_next())
        self.assertFalse(orchestrator.enqueue(FrameJob(context, b"late")))
        fresh = orchestrator.create_context("session-a", "desktop")
        self.assertNotEqual(fresh.generation, context.generation)
        self.assertTrue(orchestrator.enqueue(FrameJob(fresh, b"fresh")))

    def test_budget_is_shared_by_live_and_analysis_routes_per_session(self):
        clock = Clock()
        orchestrator = VisionFrameOrchestrator(
            max_frames_per_minute=1, min_interval_seconds=0, clock=clock
        )
        live = orchestrator.create_context("s", "desktop")
        analysis = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(live, live_ready=True).route, "live")
        self.assertEqual(
            orchestrator.decide(analysis, live_ready=False).reason, "frame_budget_exhausted"
        )
        other_session = orchestrator.create_context("other", "desktop")
        self.assertEqual(orchestrator.decide(other_session, live_ready=False).route, "analysis")

    def test_frame_context_is_immutable_and_contains_session_and_window_identity(self):
        context = FrameContext.create(
            "s", "game", {"hwnd": 3, "pid": 7, "exe": "GAME.EXE", "title": "Arena"}
        )
        self.assertEqual(context.session_id, "s")
        self.assertEqual(context.window_identity[:4], (3, 7, "game.exe", "Arena"))
        with self.assertRaises(Exception):
            context.session_id = "other"

    def test_cancelled_pending_job_is_removed_and_does_not_leak_to_another_session(self):
        orchestrator = VisionFrameOrchestrator(capacity=2)
        stale = orchestrator.create_context("session-a", "desktop")
        fresh = orchestrator.create_context("session-b", "desktop")
        orchestrator.enqueue(FrameJob(stale, b"private-a"))
        orchestrator.enqueue(FrameJob(fresh, b"private-b"))
        self.assertEqual(orchestrator.cancel_session("session-a"), 1)
        job = orchestrator.take_next()
        self.assertEqual(job.context.session_id, "session-b")
        self.assertEqual(job.payload, b"private-b")

    def test_session_generation_reports_in_flight_context_staleness(self):
        orchestrator = VisionFrameOrchestrator()
        context = orchestrator.create_context("s", "desktop")
        self.assertTrue(orchestrator.is_current(context))
        orchestrator.cancel_session("s")
        self.assertFalse(orchestrator.is_current(context))
        self.assertTrue(orchestrator.is_current(orchestrator.create_context("s", "desktop")))

    def test_cancel_invalidates_an_already_decided_frame(self):
        orchestrator = VisionFrameOrchestrator()
        context = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(context, live_ready=True).route, "live")
        orchestrator.cancel_session("s")
        stale = orchestrator.decide(context, live_ready=False)
        self.assertEqual(stale.route, "drop")
        self.assertEqual(stale.reason, "stale_session_generation")

    def test_concurrent_decisions_for_one_frame_are_idempotent(self):
        orchestrator = VisionFrameOrchestrator()
        context = orchestrator.create_context("s", "desktop")
        results = []
        barrier = threading.Barrier(8)

        def decide():
            barrier.wait()
            results.append(orchestrator.decide(context, live_ready=True))

        threads = [threading.Thread(target=decide) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 8)
        self.assertEqual({result.route for result in results}, {"live"})
        self.assertEqual(orchestrator.snapshot()["duplicate_frames"], 7)


    def test_pending_capacity_and_dispatch_are_scoped_per_session(self):
        orchestrator = VisionFrameOrchestrator(capacity=1)
        a1 = orchestrator.create_context("a", "desktop")
        a2 = orchestrator.create_context("a", "desktop")
        b1 = orchestrator.create_context("b", "desktop")
        self.assertTrue(orchestrator.enqueue(FrameJob(a1, b"a-old")))
        self.assertTrue(orchestrator.enqueue(FrameJob(b1, b"b")))
        self.assertTrue(orchestrator.enqueue(FrameJob(a2, b"a-new")))
        self.assertEqual(orchestrator.take_next("b").context.frame_id, b1.frame_id)
        self.assertEqual(orchestrator.take_next("a").context.frame_id, a2.frame_id)
        self.assertIsNone(orchestrator.take_next("a"))
        self.assertEqual(orchestrator.snapshot()["dropped_pending"], 1)

    
    def test_releasing_unsent_frame_returns_shared_quota(self):
        orchestrator = VisionFrameOrchestrator(max_frames_per_minute=1)
        context = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(context, live_ready=True).route, "live")
        self.assertTrue(orchestrator.release(context))
        next_context = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(next_context, live_ready=False).route, "analysis")

    def test_discard_removes_pending_frame_and_returns_its_quota(self):
        orchestrator = VisionFrameOrchestrator(max_frames_per_minute=1)
        context = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(context, live_ready=False).route, "analysis")
        self.assertTrue(orchestrator.enqueue(FrameJob(context, b"payload")))
        self.assertTrue(orchestrator.discard(context))
        self.assertIsNone(orchestrator.take_next("s"))
        next_context = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(next_context, live_ready=False).route, "analysis")

    def test_committing_dispatched_frame_retains_quota_without_reservation_leak(self):
        orchestrator = VisionFrameOrchestrator(max_frames_per_minute=1)
        context = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(context, live_ready=True).route, "live")
        self.assertTrue(orchestrator.commit(context))
        self.assertFalse(orchestrator.commit(context))
        next_context = orchestrator.create_context("s", "desktop")
        self.assertEqual(
            orchestrator.decide(next_context, live_ready=False).reason,
            "frame_budget_exhausted",
        )

    def test_replacing_pending_frame_releases_evicted_quota(self):
        orchestrator = VisionFrameOrchestrator(capacity=1, max_frames_per_minute=2)
        first = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(first, live_ready=False).route, "analysis")
        orchestrator.enqueue(FrameJob(first, b"old"))
        second = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(second, live_ready=False).route, "analysis")
        orchestrator.enqueue(FrameJob(second, b"new"))
        third = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(third, live_ready=False).route, "analysis")

    def test_configured_budget_is_shared_across_route_types(self):
        orchestrator = VisionFrameOrchestrator()
        orchestrator.configure_budget(max_frames_per_minute=1, min_interval_seconds=5)
        live = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(live, live_ready=True, now=100).route, "live")
        blocked = orchestrator.create_context("s", "desktop")
        self.assertEqual(
            orchestrator.decide(blocked, live_ready=False, now=102).reason,
            "frame_budget_exhausted",
        )
        orchestrator.configure_budget(max_frames_per_minute=2, min_interval_seconds=0)
        analysis = orchestrator.create_context("s", "desktop")
        self.assertEqual(orchestrator.decide(analysis, live_ready=False, now=103).route, "analysis")


if __name__ == "__main__":
    unittest.main()
