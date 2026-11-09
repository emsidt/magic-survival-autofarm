import unittest
import time
from record_human_play import MouseTracker


class TestRecordHumanPlay(unittest.TestCase):
    def test_mouse_tracker_in_rect(self):
        tracker = MouseTracker()
        rect = {"left": 100, "top": 50, "width": 800, "height": 1000}

        # Add simulated clicks
        t0 = time.monotonic()
        with tracker._lock:
            # Click inside rect (screen x=500 -> nx=0.5, screen y=730 -> ny=0.68)
            tracker.clicks.append((500, 730, t0 + 0.1))

        res = tracker.get_last_click_in_rect(rect, since_time=t0)
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res[0], 0.50, delta=0.01)
        self.assertAlmostEqual(res[1], 0.68, delta=0.01)

        tracker.clear()
        self.assertIsNone(tracker.get_last_click_in_rect(rect, since_time=t0))

    def test_card_slot_mapping(self):
        # 3-card layout tests
        # Card 1 center ~0.36
        # Card 2 center ~0.53
        # Card 3 center ~0.70
        # Mana center ~0.85
        centers_3 = {1: 0.36, 2: 0.53, 3: 0.70, "mana": 0.85}

        def map_3(norm_y):
            if 0.20 <= norm_y < 0.445:
                return 1
            elif 0.445 <= norm_y < 0.619:
                return 2
            elif 0.619 <= norm_y < 0.798:
                return 3
            elif 0.798 <= norm_y < 0.95:
                return "mana"
            return min(centers_3.keys(), key=lambda k: abs(norm_y - centers_3[k]))

        self.assertEqual(map_3(0.32), 1)  # Incineration
        self.assertEqual(map_3(0.50), 2)  # Electric Shock
        self.assertEqual(map_3(0.68), 3)  # Blizzard -> must be Card 3!
        self.assertEqual(map_3(0.83), "mana")

        # 4-card layout tests
        # Card 1: 0.15 .. 0.367
        # Card 2: 0.367 .. 0.540
        # Card 3: 0.540 .. 0.714
        # Card 4: 0.714 .. 0.890
        # Mana: 0.890 .. 0.98
        centers_4 = {1: 0.28, 2: 0.45, 3: 0.62, 4: 0.80, "mana": 0.93}

        def map_4(norm_y):
            if 0.15 <= norm_y < 0.367:
                return 1
            elif 0.367 <= norm_y < 0.540:
                return 2
            elif 0.540 <= norm_y < 0.714:
                return 3
            elif 0.714 <= norm_y < 0.890:
                return 4
            elif 0.890 <= norm_y < 0.98:
                return "mana"
            return min(centers_4.keys(), key=lambda k: abs(norm_y - centers_4[k]))

        self.assertEqual(map_4(0.25), 1)
        self.assertEqual(map_4(0.43), 2)
        self.assertEqual(map_4(0.60), 3)
        self.assertEqual(map_4(0.78), 4)
        self.assertEqual(map_4(0.93), "mana")


if __name__ == "__main__":
    unittest.main()

