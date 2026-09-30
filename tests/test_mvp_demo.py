import io
from contextlib import redirect_stdout
from types import SimpleNamespace
import unittest

from microduck_connectome.mvp_demo import DemoObserver


def _update(scenario, *, left=0.0, right=0.0, escape=0.0, stop=False):
    return SimpleNamespace(
        trace={
            "male_cns": {"scenario_fixture": scenario},
            "dn_readout": {
                "steering_left": left,
                "steering_right": right,
                "escape": escape,
            },
            "pre_safety_intent": {"stop": stop},
        }
    )


def _output(vyaw=0.0, stop=False):
    return {
        "intent": {"vyaw": vyaw, "stop": stop},
        "watchdog_state": "healthy",
    }


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
