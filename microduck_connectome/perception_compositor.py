"""P4→P6 pre-integration perception compositor and real sensor-feature pipeline."""

from collections.abc import Mapping
from dataclasses import dataclass

from .camera_target import CameraTargetDetector
from .looming import LoomingEstimator
from .perception_frame import make_perception_frame, neutral_perception_frame
from .tof import ToFProximityEncoder

PERCEPTION_TTL_MS = 100


class PerceptionCompositorError(ValueError):
    """Perception compositor configuration or source shape is invalid."""


@dataclass(frozen=True)
class PerceptionCompositorConfig:
    perception_ttl_ms: int = PERCEPTION_TTL_MS
    max_source_skew_ms: int = PERCEPTION_TTL_MS

    def __post_init__(self):
        if type(self.perception_ttl_ms) is not int or self.perception_ttl_ms != PERCEPTION_TTL_MS:
            raise PerceptionCompositorError("perception_ttl_ms must remain frozen at 100")
        if type(self.max_source_skew_ms) is not int or self.max_source_skew_ms != PERCEPTION_TTL_MS:
            raise PerceptionCompositorError("max_source_skew_ms must equal the frozen 100 ms coherence bound")


def make_looming_sample(*, looming, timestamp_ns, frame_id, valid=True):
    """Build a camera-associated looming sample with explicit identity."""
    frame = make_perception_frame(
        timestamp_ns=timestamp_ns,
        frame_id=frame_id,
        looming=looming,
        valid=valid,
    )
    return {
        "timestamp_ns": frame["timestamp_ns"],
        "frame_id": frame["frame_id"],
        "looming": frame["looming"],
        "valid": frame["valid"],
    }


class PerceptionCompositor:
    """Join camera-associated looming and asynchronous ToF into one frozen frame."""

    def __init__(self, config=None):
        self.config = config or PerceptionCompositorConfig()
        if not isinstance(self.config, PerceptionCompositorConfig):
            raise PerceptionCompositorError("config must be PerceptionCompositorConfig")
        self.reset()

    def reset(self):
        self._last_camera_meta = None
        self._last_tof_meta = None
        self._last_reasons = ()

    @property
    def last_reasons(self):
        return self._last_reasons

    @staticmethod
    def _canonical_frame(value, label):
        if not isinstance(value, Mapping):
            raise PerceptionCompositorError(f"{label} must be a perception-frame mapping")
        try:
            return make_perception_frame(**dict(value))
        except (TypeError, ValueError) as error:
            raise PerceptionCompositorError(f"{label} violates the frozen perception-frame contract") from error

    @staticmethod
    def _looming(value):
        required = {"timestamp_ns", "frame_id", "looming", "valid"}
        if not isinstance(value, Mapping) or set(value) != required:
            raise PerceptionCompositorError("looming sample fields mismatch")
        try:
            canonical = make_looming_sample(**dict(value))
        except (TypeError, ValueError) as error:
            raise PerceptionCompositorError("looming sample violates the frozen contract") from error
        return canonical

    @staticmethod
    def _same_or_advancing(current, previous):
        if previous is None:
            return True
        current_ts, current_id = current
        previous_ts, previous_id = previous
        return (
            (current_ts == previous_ts and current_id == previous_id)
            or (current_ts > previous_ts and current_id > previous_id)
        )

    def _neutral(self, *, timestamp_ns, frame_id, reasons):
        self._last_reasons = tuple(reasons)
        return neutral_perception_frame(
            timestamp_ns=timestamp_ns,
            frame_id=frame_id,
            valid=False,
        )

    def compose(self, camera_frame, looming_sample, tof_frame, *, now_ns):
        if type(now_ns) is not int or now_ns < 0:
            raise PerceptionCompositorError("now_ns must be a non-negative integer")

        camera = self._canonical_frame(camera_frame, "camera_frame")
        looming = self._looming(looming_sample)
        tof = self._canonical_frame(tof_frame, "tof_frame")

        camera_meta = (camera["timestamp_ns"], camera["frame_id"])
        tof_meta = (tof["timestamp_ns"], tof["frame_id"])
        reasons = []

        if not self._same_or_advancing(camera_meta, self._last_camera_meta):
            reasons.append("nonmonotonic_camera")
        if not self._same_or_advancing(tof_meta, self._last_tof_meta):
            reasons.append("nonmonotonic_tof")

        # A new frame ID at an identical timestamp (or vice versa) is incoherent.
        if self._last_camera_meta is not None:
            last_ts, last_id = self._last_camera_meta
            if (camera["timestamp_ns"] == last_ts) != (camera["frame_id"] == last_id):
                reasons.append("camera_identity_mismatch")
        if self._last_tof_meta is not None:
            last_ts, last_id = self._last_tof_meta
            if (tof["timestamp_ns"] == last_ts) != (tof["frame_id"] == last_id):
                reasons.append("tof_identity_mismatch")

        # Looming is derived from the camera stream and must identify that exact visual frame.
        if (
            looming["timestamp_ns"] != camera["timestamp_ns"]
            or looming["frame_id"] != camera["frame_id"]
        ):
            reasons.append("looming_camera_identity_mismatch")

        for label, source in (("camera", camera), ("looming", looming), ("tof", tof)):
            if source["timestamp_ns"] > now_ns:
                reasons.append(f"future_{label}")
            elif now_ns - source["timestamp_ns"] > self.config.perception_ttl_ms * 1_000_000:
                reasons.append(f"stale_{label}")

        if abs(camera["timestamp_ns"] - tof["timestamp_ns"]) > self.config.max_source_skew_ms * 1_000_000:
            reasons.append("source_skew")

        if not camera["valid"]:
            reasons.append("invalid_camera")
        if not looming["valid"]:
            reasons.append("invalid_looming")
        if not tof["valid"]:
            reasons.append("invalid_tof")

        # Retain source metadata even for a fault so repeated evaluation cannot refresh source age.
        if self._same_or_advancing(camera_meta, self._last_camera_meta):
            self._last_camera_meta = camera_meta
        if self._same_or_advancing(tof_meta, self._last_tof_meta):
            self._last_tof_meta = tof_meta

        output_timestamp = max(camera["timestamp_ns"], tof["timestamp_ns"])
        output_frame_id = camera["frame_id"]

        if reasons:
            return self._neutral(
                timestamp_ns=output_timestamp,
                frame_id=output_frame_id,
                reasons=reasons,
            )

        self._last_reasons = ()
        return make_perception_frame(
            timestamp_ns=output_timestamp,
            frame_id=output_frame_id,
            target_x=camera["target_x"],
            target_area=camera["target_area"],
            looming=looming["looming"],
            proximity_left=tof["proximity_left"],
            proximity_center=tof["proximity_center"],
            proximity_right=tof["proximity_right"],
            confidence=camera["confidence"],
            valid=True,
        )


class PerceptionPipeline:
    """Exercise the real P4-01/02/03 components before composing their outputs."""

    def __init__(
        self,
        camera_detector=None,
        looming_estimator=None,
        tof_encoder=None,
        compositor=None,
    ):
        self.camera_detector = camera_detector or CameraTargetDetector()
        self.looming_estimator = looming_estimator or LoomingEstimator()
        self.tof_encoder = tof_encoder or ToFProximityEncoder()
        self.compositor = compositor or PerceptionCompositor()

    def reset(self):
        self.looming_estimator.reset()
        self.compositor.reset()

    def process(
        self,
        camera_pixels,
        *,
        camera_timestamp_ns,
        camera_frame_id,
        tof_left_mm,
        tof_center_mm,
        tof_right_mm,
        tof_timestamp_ns,
        tof_frame_id,
        now_ns,
        camera_source_valid=True,
        tof_source_valid=True,
    ):
        camera = self.camera_detector.detect(
            camera_pixels,
            timestamp_ns=camera_timestamp_ns,
            frame_id=camera_frame_id,
            source_valid=camera_source_valid,
        )

        camera_fresh = (
            type(now_ns) is int
            and now_ns >= camera_timestamp_ns
            and now_ns - camera_timestamp_ns <= self.compositor.config.perception_ttl_ms * 1_000_000
        )

        # Looming is meaningful only while a fresh valid target observation exists.
        looming_valid = camera["valid"] and camera_fresh and camera["target_area"] > 0.0
        if not looming_valid:
            self.looming_estimator.reset()
            looming_value = 0.0
        else:
            looming_value = self.looming_estimator.update(
                camera["target_area"],
                timestamp_ns=camera_timestamp_ns,
                valid=True,
            )
        looming = make_looming_sample(
            looming=looming_value,
            timestamp_ns=camera_timestamp_ns,
            frame_id=camera_frame_id,
            valid=camera["valid"] and camera_fresh,
        )

        tof = self.tof_encoder.encode(
            left_mm=tof_left_mm,
            center_mm=tof_center_mm,
            right_mm=tof_right_mm,
            timestamp_ns=tof_timestamp_ns,
            frame_id=tof_frame_id,
            source_valid=tof_source_valid,
        )

        return self.compositor.compose(camera, looming, tof, now_ns=now_ns)
