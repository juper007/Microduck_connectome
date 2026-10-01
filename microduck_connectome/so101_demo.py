"""Real graph-v2 -> existing DN decoder/watchdog -> simulated SO-101."""
import argparse
import json
from pathlib import Path
import time

from .graph import ConnectomeGraph
from .mvp_demo import MvpChain, resolve_graph
from .scheduler import ClosedLoopScheduler
from .watchdog import ControllerWatchdog
from .so101_sim import MockArm, MujocoArm, SO101SimAdapter, TaskIntent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("mock", "mujoco"), default="mock")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/so101-demo"))
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    cache,key = resolve_graph(root, None, None)
    graph = ConnectomeGraph.from_cache(cache,key)
    chain = MvpChain(root,graph,turn_s=3,stop_s=3)
    if args.backend == "mujoco" and args.model_dir is None:
        parser.error("--model-dir required for mujoco")
    backend = MockArm() if args.backend == "mock" else MujocoArm(args.model_dir)
    adapter = SO101SimAdapter(backend)
    args.output.mkdir(parents=True,exist_ok=True)
    rows = []

    def publish(output):
        intent = output["intent"]
        # Existing temporal DNa02 differential decoder, safety and watchdog
        # remain upstream. Yaw is normalized into an engineering orient bias.
        task = TaskIntent(intent["timestamp_ns"],intent["sequence"],
                          max(-1,min(1,intent["vyaw"]/0.3)),
                          intent["stop"] or output["watchdog_state"] != "healthy",
                          intent["confidence"])
        return adapter.send(task,now_ns=time.monotonic_ns())

    def observe(update,output,result):
        if update is None:
            return
        trace = update.trace
        rows.append({"scenario":trace["male_cns"]["scenario_fixture"],
                     "dn":dict(update.readout),"watchdog":output["watchdog_state"],
                     "stop":output["intent"]["stop"],
                     "pre_stop":trace["pre_safety_intent"]["stop"],**result})

    scheduler = ClosedLoopScheduler(config=root/"config/scheduler_v1.json",
        watchdog=ControllerWatchdog(root/"config/watchdog_v1.json"),
        perception_step=chain.perception,neural_step=chain.neural,
        publisher=publish,control_observer=observe)
    try:
        stats = scheduler.run(chain.scenario_duration_s+0.4)
    finally:
        adapter.close()
        (args.output/"telemetry.json").write_text(json.dumps(rows))
    by_phase = {p:[r for r in rows if r["scenario"]==p] for p in chain.scenarios}
    motion = {}
    for phase in ("left","right"):
        r = by_phase[phase]
        motion[phase] = {"delta_rad":r[-1]["q"][0]-r[0]["q"][0],
                         "velocity_peak_rad_s":max((x["v"][0] for x in r),key=abs)}
    stop_rows = by_phase["stop"]
    escape = any(r["dn"]["escape"]>=0.5 and r["pre_stop"] and r["stop"]
                 and r["hold"] and r["watchdog"]=="healthy" for r in stop_rows)
    tail = stop_rows[-25:]
    drift = max(r["q"][0] for r in tail)-min(r["q"][0] for r in tail)
    velocity = max(abs(r["v"][0]) for r in tail)
    held_targets = len({r["target"][0] for r in tail}) == 1
    nonpan_error = max(abs(r["q"][i]-r["target"][i]) for r in rows for i in range(1,6))
    passed = (motion["left"]["delta_rad"]>0.01 and motion["right"]["delta_rad"] < -0.01
              and motion["left"]["velocity_peak_rad_s"]>0.01
              and motion["right"]["velocity_peak_rad_s"]< -0.01
              and escape and held_targets and drift<0.002 and velocity<0.01
              and nonpan_error<0.04 and not any(r["fault"] for r in rows))
    summary = {"result":"PASS" if passed else "INCOMPLETE","backend":args.backend,
        "graph_key":key,"motion":motion,"neural_escape_hold":escape,
        "final_hold_drift_rad":drift,"final_hold_velocity_rad_s":velocity,
        "held_target":held_targets,"nonpan_max_tracking_error_rad":nonpan_error,
        "scheduler_exceptions":stats["scheduler_exceptions"],
        "scope":"engineering arm mapping; no biological arm-control validation or G11 claim"}
    if args.backend == "mujoco":
        # Render recorded actual simulator states after control stops, so GPU
        # rendering cannot block the control/watchdog thread.
        for phase in ("neutral","left","right","stop"):
            state = by_phase[phase][-1]
            backend.data.qpos[backend.qids] = state["q"]
            backend.data.qvel[backend.vids] = state["v"]
            backend.mj.mj_forward(backend.model,backend.data)
            backend.render(args.output/f"{phase}.png")
    (args.output/"summary.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
