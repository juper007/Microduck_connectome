import io
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest

from microduck_connectome.mvp_demo import DemoObserver, MvpChain, phase_frame_counts
from microduck_connectome.perception_compositor import PerceptionPipeline


def _update(scenario, *, left=0.0, right=0.0, escape=0.0, stop=False):
    return SimpleNamespace(
        trace={
            "male_cns": {"scenario_fixture": scenario},
            "dn_readout": {
                "steering_left": left,
                "steering_right": right,
                "escape": escape,
            },
            "pre_safety_intent": {"stop": stop, "vyaw": left - right},
        }
    )


def _output(vyaw=0.0, stop=False):
    return {
        "intent": {"vyaw": vyaw, "stop": stop},
        "watchdog_state": "healthy",
    }


class PhaseTimingTests(unittest.TestCase):
    def test_sustained_turns_extend_actual_stimulus_phases(self):
        chain = object.__new__(MvpChain)
        chain.phase_frames = phase_frame_counts(8, 3, 25)
        chain.scenarios = ("neutral", "left", "right", "center", "stop")
        chain.pipeline = PerceptionPipeline()
        chain.frame_id = 0
        observed = {}
        for frame_id in range(1, 537):
            frame = chain.perception(frame_id * 40_000_000)
            observed[frame_id] = (chain.scenario, frame["target_x"])
        self.assertEqual(observed[30][0], "neutral")
        self.assertEqual(observed[31], ("left", -1.0))
        self.assertEqual(observed[230], ("left", -1.0))
        self.assertEqual(observed[231], ("right", 1.0))
        self.assertEqual(observed[430], ("right", 1.0))
        self.assertEqual(observed[431][0], "center")
        self.assertEqual(observed[461][0], "stop")
        self.assertEqual(observed[536][0], "stop")

    def test_quick_mode_and_fractional_seconds(self):
        self.assertEqual(phase_frame_counts(1.2, 1.2, 25), (30, 30, 30, 30, 30))
        self.assertEqual(phase_frame_counts(1.21, 3, 25), (30, 31, 31, 30, 75))

    def test_repeated_phases_are_scheduled_before_final_stop(self):
        chain = object.__new__(MvpChain)
        chain.phase_frames = phase_frame_counts(8, 3, 25, 2)
        chain.scenarios = ("neutral", "left", "right", "left", "right", "center", "stop")
        chain.pipeline = PerceptionPipeline()
        chain.frame_id = 0
        observed = {}
        for frame_id in range(1, 862):
            chain.perception(frame_id * 40_000_000)
            observed[frame_id] = chain.scenario
        self.assertEqual(observed[430], "right")
        self.assertEqual(observed[431], "left")
        self.assertEqual(observed[630], "left")
        self.assertEqual(observed[631], "right")
        self.assertEqual(observed[830], "right")
        self.assertEqual(observed[831], "center")
        self.assertEqual(observed[861], "stop")
        for cycles in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                phase_frame_counts(8, 3, 25, cycles)

    def test_invalid_phase_duration_is_rejected(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    phase_frame_counts(value, 3, 25)
                with self.assertRaises(ValueError):
                    phase_frame_counts(8, value, 25)


class DemoObserverTests(unittest.TestCase):
    def test_passes_on_opposite_turns_and_neural_escape(self):
        observer = DemoObserver()
        output = io.StringIO()
        with redirect_stdout(output):
            observer(_update("left", left=0.8), _output(vyaw=0.2), "move")
            observer(_update("right", right=0.8), _output(vyaw=-0.2), "move")
            observer(
                _update("stop", escape=0.7, stop=True),
                _output(stop=True),
                "robot_stop_refreshed",
            )

        summary = observer.summary()
        self.assertEqual(summary["demo_result"], "PASS")
        self.assertTrue(summary["opposite_left_right_turns"])
        self.assertTrue(summary["connectome_escape_stop_seen"])
        self.assertIn("neural_escape", output.getvalue())
        self.assertEqual(output.getvalue().count('"event": "turn"'), 2)

    def test_unproven_turn_commands_do_not_pass(self):
        cases = ((0.0, "healthy", "move"), (0.8, "fault", "move"), (0.8, "healthy", "failed"))
        for dn, watchdog, transport in cases:
            with self.subTest(dn=dn, watchdog=watchdog, transport=transport):
                observer = DemoObserver()
                left, right = _output(vyaw=0.2), _output(vyaw=-0.2)
                left["watchdog_state"] = right["watchdog_state"] = watchdog
                with redirect_stdout(io.StringIO()):
                    observer(_update("left", left=dn), left, transport)
                    observer(_update("right", right=dn), right, transport)
                    observer(_update("stop", escape=0.7, stop=True), _output(stop=True), "robot_stop_refreshed")
                self.assertFalse(observer.summary()["opposite_left_right_turns"])

    def test_latest_equal_peak_wins_after_direction_transition(self):
        self.assertEqual(DemoObserver._peak([0.5, 0.1, -0.5]), -0.5)

    def test_fault_stop_and_unacknowledged_stop_are_not_neural_escape(self):
        for watchdog, transport in (("fault", "robot_stop_refreshed"), ("healthy", "failed")):
            with self.subTest(watchdog=watchdog, transport=transport):
                observer = DemoObserver()
                output = _output(stop=True)
                output["watchdog_state"] = watchdog
                with redirect_stdout(io.StringIO()):
                    observer(_update("stop", escape=0.7, stop=True), output, transport)
                self.assertFalse(observer.summary()["connectome_escape_stop_seen"])

    def test_shutdown_stop_is_not_counted_as_neural_escape(self):
        observer = DemoObserver()
        with redirect_stdout(io.StringIO()):
            observer(_update("left"), _output(vyaw=0.2), "move")
            observer(_update("right"), _output(vyaw=-0.2), "move")
            observer(
                _update("stop", escape=0.0, stop=False),
                _output(stop=True),
                "robot_stop_refreshed",
            )

        summary = observer.summary()
        self.assertEqual(summary["demo_result"], "INCOMPLETE")
        self.assertFalse(summary["connectome_escape_stop_seen"])


if __name__ == "__main__":
    unittest.main()
