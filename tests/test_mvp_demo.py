from types import SimpleNamespace

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


def test_demo_observer_passes_on_opposite_turns_and_neural_escape(capsys):
    observer = DemoObserver()
    observer(_update("left", left=0.8), _output(vyaw=0.2), "move")
    observer(_update("right", right=0.8), _output(vyaw=-0.2), "move")
    observer(
        _update("stop", escape=0.7, stop=True),
        _output(stop=True),
        "robot_stop_refreshed",
    )

    summary = observer.summary()
    assert summary["demo_result"] == "PASS"
    assert summary["opposite_left_right_turns"] is True
    assert summary["connectome_escape_stop_seen"] is True
    assert "neural_escape" in capsys.readouterr().out


def test_demo_observer_does_not_count_shutdown_stop_as_neural_escape():
    observer = DemoObserver()
    observer(_update("left"), _output(vyaw=0.2), "move")
    observer(_update("right"), _output(vyaw=-0.2), "move")
    observer(_update("stop", escape=0.0, stop=False), _output(stop=True), "robot_stop_refreshed")

    summary = observer.summary()
    assert summary["demo_result"] == "INCOMPLETE"
    assert summary["connectome_escape_stop_seen"] is False
