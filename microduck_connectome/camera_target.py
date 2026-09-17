"""Dependency-free synthetic/high-contrast RGB target detector for P4-01."""

from collections.abc import Sequence
from dataclasses import dataclass

from .perception_frame import make_perception_frame, neutral_perception_frame


class CameraTargetError(ValueError):
    """Camera target configuration or frame data is invalid."""


@dataclass(frozen=True)
class CameraTargetConfig:
    target_rgb: tuple[int, int, int] = (255, 0, 0)
    tolerance: int = 0
    min_pixels: int = 1

    def __post_init__(self):
        if (
            not isinstance(self.target_rgb, tuple)
            or len(self.target_rgb) != 3
            or any(type(channel) is not int or not 0 <= channel <= 255 for channel in self.target_rgb)
        ):
            raise CameraTargetError("target_rgb must be a 3-tuple of integer channels in [0,255]")
        if type(self.tolerance) is not int or not 0 <= self.tolerance <= 255:
            raise CameraTargetError("tolerance must be an integer in [0,255]")
        if type(self.min_pixels) is not int or self.min_pixels <= 0:
            raise CameraTargetError("min_pixels must be a positive integer")


class CameraTargetDetector:
    """Detect one configured marker and emit frozen perception-frame target fields."""

    def __init__(self, config=None):
        self.config = config or CameraTargetConfig()

    def _validate_frame(self, frame):
        if not isinstance(frame, Sequence) or isinstance(frame, (str, bytes)) or not frame:
            raise CameraTargetError("frame must be a non-empty row sequence")
        width = None
        normalized = []
        for row in frame:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or not row:
                raise CameraTargetError("each frame row must be a non-empty pixel sequence")
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise CameraTargetError("frame rows must have equal width")
            pixels = []
            for pixel in row:
                if (
                    not isinstance(pixel, Sequence)
                    or isinstance(pixel, (str, bytes))
                    or len(pixel) != 3
                    or any(type(channel) is not int or not 0 <= channel <= 255 for channel in pixel)
                ):
                    raise CameraTargetError("pixels must be RGB integer triples in [0,255]")
                pixels.append(tuple(pixel))
            normalized.append(tuple(pixels))
        return tuple(normalized), width, len(normalized)

    def detect(self, frame, *, timestamp_ns, frame_id, source_valid=True):
        if type(source_valid) is not bool:
            raise CameraTargetError("source_valid must be bool")
        if not source_valid:
            return neutral_perception_frame(
                timestamp_ns=timestamp_ns,
                frame_id=frame_id,
                valid=False,
            )

        frame, width, height = self._validate_frame(frame)
        target = self.config.target_rgb
        tolerance = self.config.tolerance
        xs = []
        for y, row in enumerate(frame):
            del y
            for x, pixel in enumerate(row):
                if all(abs(pixel[i] - target[i]) <= tolerance for i in range(3)):
                    xs.append(x)

        if len(xs) < self.config.min_pixels:
            return neutral_perception_frame(
                timestamp_ns=timestamp_ns,
                frame_id=frame_id,
                valid=True,
            )

        centroid_x = sum(xs) / len(xs)
        target_x = 0.0 if width == 1 else (2.0 * centroid_x / (width - 1)) - 1.0
        target_x = max(-1.0, min(1.0, target_x))
        target_area = len(xs) / (width * height)
        return make_perception_frame(
            timestamp_ns=timestamp_ns,
            frame_id=frame_id,
            target_x=target_x,
            target_area=target_area,
            confidence=1.0,
            valid=True,
        )
