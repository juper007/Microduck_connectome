"""Simulation-only SO-101 adapter; engineering mapping, no hardware access."""
from dataclasses import dataclass
import math
from pathlib import Path
import subprocess

MODEL_PIN = "4d038b3feae26ec82b46a4d586379114012a8ac7"
JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
POSE = (0.0, -0.5, 0.5, 0.0, 0.0, 0.5)


@dataclass(frozen=True)
class TaskIntent:
    """Minimal orient/hold subset of the planned P11 task boundary."""
    timestamp_ns: int
    sequence: int
    horizontal_bias: float = 0.0
    stop: bool = True
    confidence: float = 1.0

    def validate(self, now_ns):
        if (type(self.timestamp_ns) is not int or type(self.sequence) is not int
                or self.sequence < 0 or not 0 <= self.timestamp_ns <= now_ns
                or now_ns - self.timestamp_ns > 100_000_000
                or type(self.stop) is not bool
                or isinstance(self.horizontal_bias, bool)
                or not math.isfinite(self.horizontal_bias) or abs(self.horizontal_bias) > 1
                or isinstance(self.confidence, bool)
                or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1):
            raise ValueError("invalid or stale task intent")


class MockArm:
    """Deterministic dry-run fixture, never a physical Robot implementation."""
    def __init__(self):
        self.connected = False
        self.q = list(POSE)
        self.v = [0.0] * 6

    def connect(self):
        self.connected = True

    def observe(self):
        if not self.connected:
            raise RuntimeError("disconnected")
        return tuple(self.q), tuple(self.v)

    def step(self, targets, dt):
        self.v = [(b-a)/dt for a,b in zip(self.q, targets)]
        self.q = list(targets)
        return self.observe()

    def close(self):
        self.connected = False


class MujocoArm(MockArm):
    def __init__(self, model_dir):
        import mujoco
        import numpy as np
        if tuple(map(int, mujoco.__version__.split(".")[:3])) < (3, 1, 3):
            raise RuntimeError("MuJoCo >=3.1.3 required")
        model_dir = Path(model_dir).resolve()
        pin = subprocess.check_output(["git", "-C", str(model_dir.parent), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(model_dir.parent), "status", "--porcelain", "--", model_dir.name], text=True)
        if pin != MODEL_PIN or dirty:
            raise RuntimeError("official model pin/cleanliness mismatch")
        self.mj = mujoco
        self.model = mujoco.MjModel.from_xml_path(str(model_dir / "scene.xml"))
        self.data = mujoco.MjData(self.model)
        self.connected = False
        self.jids = [self.model.joint(n).id for n in JOINTS]
        self.aids = [self.model.actuator(n).id for n in JOINTS]
        self.qids = [int(self.model.jnt_qposadr[j]) for j in self.jids]
        self.vids = [int(self.model.jnt_dofadr[j]) for j in self.jids]
        if self.model.nq != 6 or self.model.nu != 6:
            raise RuntimeError("unexpected SO-101 dimensions")
        for j,a,p in zip(self.jids,self.aids,POSE):
            if (self.model.jnt_type[j] != mujoco.mjtJoint.mjJNT_HINGE
                    or self.model.actuator_trnid[a,0] != j
                    or self.model.actuator_trntype[a] != mujoco.mjtTrn.mjTRN_JOINT
                    or not np.allclose(self.model.actuator_gear[a], [1,0,0,0,0,0])
                    or self.model.actuator_gainprm[a,0] <= 0
                    or not np.isclose(self.model.actuator_biasprm[a,1], -self.model.actuator_gainprm[a,0])
                    or not self.model.jnt_range[j,0] <= p <= self.model.jnt_range[j,1]
                    or not self.model.actuator_ctrlrange[a,0] <= p <= self.model.actuator_ctrlrange[a,1]):
                raise RuntimeError("joint/position actuator semantics mismatch")
        self.data.qpos[self.qids] = POSE
        self.data.ctrl[self.aids] = POSE
        mujoco.mj_forward(self.model, self.data)

    def observe(self):
        if not self.connected:
            raise RuntimeError("disconnected")
        q = tuple(float(self.data.qpos[i]) for i in self.qids)
        v = tuple(float(self.data.qvel[i]) for i in self.vids)
        if not all(math.isfinite(x) for x in q+v):
            raise RuntimeError("nonfinite simulation state")
        return q,v

    def step(self, targets, dt):
        self.observe()
        self.data.ctrl[self.aids] = targets
        steps = round(dt / self.model.opt.timestep)
        if steps < 1 or not math.isclose(steps*self.model.opt.timestep, dt):
            raise ValueError("control interval must align with physics timestep")
        for _ in range(steps):
            self.mj.mj_step(self.model, self.data)
        return self.observe()

    def render(self, path):
        from PIL import Image
        with self.mj.Renderer(self.model, height=480, width=640) as renderer:
            camera = self.mj.MjvCamera()
            camera.lookat[:] = [0,0,0.18]
            camera.distance, camera.azimuth, camera.elevation = 0.8, 140, -25
            renderer.update_scene(self.data, camera=camera)
            Image.fromarray(renderer.render()).save(path)


class SO101SimAdapter:
    """Owns bounded joint targets. Faults latch until a new adapter is created.

    Only shoulder pan moves: 0.2 rad/s maximum, +/-0.4 rad envelope.
    A hold freezes the target at observed pan once; physics continues settling.
    No LeRobot, motor bus, robotd or physical device connection exists here.
    """
    def __init__(self, backend):
        self.backend = backend
        self.target = list(POSE)
        self.holding = True
        self.fault = None
        self.last_sequence = -1
        self.last_now = None
        try:
            backend.connect()
            backend.observe()
        except Exception:
            backend.close()
            raise

    def hold(self):
        if not self.holding:
            try:
                self.target[0] = max(-0.4, min(0.4, self.backend.observe()[0][0]))
            finally:
                self.holding = True

    def send(self, intent, *, now_ns, dt=0.02):
        try:
            intent.validate(now_ns)
            if self.last_now is not None and now_ns - self.last_now > 100_000_000:
                raise ValueError("control gap")
            if (not math.isfinite(dt) or not 0 < dt <= 0.02
                    or intent.sequence <= self.last_sequence
                    or self.last_now is not None and now_ns <= self.last_now):
                raise ValueError("rate/sequence violation")
            self.last_sequence, self.last_now = intent.sequence, now_ns
            q,v = self.backend.observe()
            if abs(q[0]) > 0.45:
                raise RuntimeError("observed pan envelope exceeded")
            if self.fault or intent.stop or intent.confidence <= 0:
                self.hold()
            else:
                self.holding = False
                self.target[0] = max(-0.4, min(0.4, self.target[0] + intent.horizontal_bias*0.2*dt))
            q,v = self.backend.step(self.target, dt)
            return {"q": q, "v": v, "target": tuple(self.target), "hold": self.holding, "fault": self.fault}
        except Exception as error:
            self.fault = self.fault or type(error).__name__
            try:
                self.hold()
                self.backend.step(self.target, 0.02)
            except Exception:
                self.backend.close()
            raise

    def close(self):
        try:
            self.hold()
            if self.backend.connected:
                self.backend.step(self.target, 0.02)
        finally:
            self.backend.close()
