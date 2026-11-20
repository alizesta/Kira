import unittest

from kira import perch
from kira.perch import Rect, Surface


class PerchGeometryTests(unittest.TestCase):
    def test_covered_top_edge_only_offers_the_visible_part(self):
        front = Rect(1, 0, 100, 500, 600)               # topmost
        back = Rect(2, 300, 80, 1000, 700)              # its top edge (y=80) is above the front window: fully visible
        hidden = Rect(3, 100, 300, 900, 800)            # top edge y=300 lies behind `front` on x 100..500
        edges = perch.visible_top_edges([front, back, hidden])
        by_handle = {}
        for s in edges:
            by_handle.setdefault(s.handle, []).append((s.left, s.right))
        self.assertEqual(by_handle[2], [(300, 1000)])
        self.assertNotIn(3, by_handle)                  # `back` also covers it
        only_front = perch.visible_top_edges([front, hidden])
        self.assertEqual([(e.left, e.right) for e in only_front if e.handle == 3], [(500, 900)])

    def test_tiny_and_screen_top_windows_are_ignored(self):
        self.assertEqual(perch.visible_top_edges([Rect(1, 0, 0, 800, 600), Rect(2, 10, 50, 60, 90)]), [])

    def test_falling_character_lands_on_the_highest_surface_below_her_feet(self):
        floor = Surface(0, 1920, 1040, "floor")
        windows = [Surface(100, 700, 400, "window", 1), Surface(100, 700, 700, "window", 2), Surface(900, 1200, 300, "window", 3)]
        self.assertEqual(perch.landing_surface(300, 200, windows, floor).handle, 1)
        self.assertEqual(perch.landing_surface(300, 500, windows, floor).handle, 2)    # already below the first window
        self.assertEqual(perch.landing_surface(300, 800, windows, floor), floor)
        self.assertEqual(perch.landing_surface(1500, 100, windows, floor), floor)       # nothing under x

    def test_sitting_places_the_hips_on_the_edge_and_keeps_part_of_her_over_it(self):
        s = Surface(100, 700, 400, "window", 1)
        x, y = perch.place_sitting(300, 600, 150, s)
        self.assertAlmostEqual(perch.hips_y(y, 600), 400, delta=1)
        self.assertGreaterEqual(x, s.left - 100)
        x2, _ = perch.place_sitting(300, 600, 5000, s)
        self.assertLessEqual(x2, s.right - 200)

    def test_windows_lookup_is_empty_off_windows(self):
        import sys
        if sys.platform != "win32":
            self.assertEqual(perch.windows_rects(), [])


if __name__ == "__main__":
    unittest.main()
