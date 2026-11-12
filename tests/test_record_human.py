import unittest
import time
from unittest.mock import patch, Mock
import main
from record_human_play import MouseTracker, MovementTracker, map_click_to_card, format_game_time


class TestRecordHumanPlay(unittest.TestCase):
    def test_format_game_time(self):
        self.assertEqual(format_game_time(0), "00:00")
        self.assertEqual(format_game_time(59), "00:59")
        self.assertEqual(format_game_time(60), "01:00")
        self.assertEqual(format_game_time(346.8), "05:46")
        self.assertEqual(format_game_time(1250), "20:50")

    def test_locate_game_ldplayer_priority(self):
        windows = [
            (101, "Magic Survival - Antigravity IDE", "HwndWrapper[DefaultDomain]"),
            (102, "LDPlayer-1", "LDPlayerMainFrame"),
            (103, "Task Manager", "TaskManagerWindow"),
        ]

        def mock_enum_windows(callback, extra):
            for hwnd, text, cls in windows:
                callback(hwnd, extra)

        with patch("main.win32gui.EnumWindows", side_effect=mock_enum_windows), \
             patch("main.win32gui.IsWindowVisible", return_value=True), \
             patch("main.win32gui.GetWindowText", side_effect=lambda h: next(t for hw, t, c in windows if hw == h)), \
             patch("main.win32gui.GetClassName", side_effect=lambda h: next(c for hw, t, c in windows if hw == h)), \
             patch("main.win32gui.GetClientRect", return_value=(0, 0, 720, 1280)), \
             patch("main.win32gui.IsIconic", return_value=False):
            found = main.locate_game("Magic Survival")
            self.assertEqual(found, 102)

    def test_game_rectangle_detects_render_window(self):
        child_windows = [
            (201, "RenderWindow", "RenderWindow", (0, 0, 720, 1280), (100, 50)),
            (202, "Toolbar", "AwtWindow", (0, 0, 40, 1280), (820, 50)),
        ]

        def mock_enum_child(parent, callback, extra):
            for hwnd, text, cls, rect, pos in child_windows:
                callback(hwnd, extra)

        with patch("main.win32gui.EnumChildWindows", side_effect=mock_enum_child), \
             patch("main.win32gui.GetClassName", side_effect=lambda h: next(c for hw, t, c, r, p in child_windows if hw == h)), \
             patch("main.win32gui.GetWindowText", side_effect=lambda h: next(t for hw, t, c, r, p in child_windows if hw == h)), \
             patch("main.win32gui.GetClientRect", side_effect=lambda h: next(r for hw, t, c, r, p in child_windows if hw == h)), \
             patch("main.win32gui.ClientToScreen", side_effect=lambda h, pt: next(p for hw, t, c, r, p in child_windows if hw == h)):
            rect = main.game_rectangle(102, {"crop_left_px": 65})
            self.assertEqual(rect, {"left": 100, "top": 50, "width": 720, "height": 1280})

    def test_is_game_or_popup_active_parent_and_child(self):
        # Foreground is child RenderWindow (201) while tracking LDPlayer main (102)
        with patch("main.win32gui.GetForegroundWindow", return_value=201), \
             patch("main.win32gui.IsChild", side_effect=lambda parent, child: parent == 102 and child == 201):
            is_active, target = main.is_game_or_popup_active(102)
            self.assertTrue(is_active)
            self.assertEqual(target, 102)

        # Foreground is LDPlayer main (102) while tracking RenderWindow (201)
        with patch("main.win32gui.GetForegroundWindow", return_value=102), \
             patch("main.win32gui.IsChild", side_effect=lambda parent, child: parent == 102 and child == 201):
            is_active, target = main.is_game_or_popup_active(201)
            self.assertTrue(is_active)
            self.assertEqual(target, 201)

    def test_finish_match_summary_for_human_recorder(self):
        import numpy as np
        from game_actions import finish_match
        from data_recorder import DataRecorder
        from learning_engine import get_adaptive_learner

        rec = DataRecorder(enabled=False)
        learner = get_adaptive_learner()
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

        rep = finish_match(
            rec, learner, dummy_frame,
            survival_seconds=346.0,
            active_skills={"spirit", "cyclone"},
            core_skills=["spirit"],
            skill_levels={"spirit": 3, "cyclone": 1},
            character="summoner",
            game_map="depth",
        )
        self.assertIsNotNone(rep)
        self.assertIn("summary_text", rep)
        self.assertIn("Depth", rep["summary_text"])
        self.assertIn("1.24", rep["summary_text"])
        self.assertIn("05:46", rep["summary_text"])
        self.assertIn("Spirit", rep["summary_text"])

    def test_mouse_tracker_in_rect(self):
        tracker = MouseTracker()
        self.addCleanup(tracker.close)
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

    def test_missing_or_non_card_click_is_unknown(self):
        for click in (None, (0.9, 0.14), (0.98, 0.35), (0.5, 0.99)):
            self.assertIsNone(map_click_to_card(click, 3))
        self.assertEqual(map_click_to_card((0.5, 0.68), 3), 3)
        self.assertEqual(map_click_to_card((0.5, 0.78), 4), 4)

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

    def test_movement_tracker_analyze_weave(self):
        tracker = MovementTracker()
        self.addCleanup(tracker.close)

        # Default profile when not enough samples
        freq, amp = tracker.analyze_weave_profile()
        self.assertEqual(freq, 3.2)
        self.assertEqual(amp, 0.28)

        # Feed simulated weaving vectors oscillating between (1, 0.3) and (1, -0.3)
        t0 = time.monotonic()
        with tracker._lock:
            for i in range(30):
                vy = 0.35 if (i % 2 == 0) else -0.35
                vx = 0.93
                tracker.vectors.append((vx, vy, t0 + i * 0.10))

        f_learned, a_learned = tracker.analyze_weave_profile()
        self.assertGreater(f_learned, 1.0)
        self.assertGreater(a_learned, 0.15)


if __name__ == "__main__":
    unittest.main()

