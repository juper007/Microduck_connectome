"""Versioned fractional-coverage RGB fixture and target detector for P8-R3.

The renderer retains the P8 virtual sphere geometry but encodes subpixel disk
coverage in red intensity. The detector receives RGB only, never evaluator
distance or sphere state. Existing binary RGB functions remain unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

from .camera_target import CameraTargetError
from .looming_scenario import LoomingScenarioError, sphere_center, validate_pose
from .perception_frame import make_perception_frame, neutral_perception_frame


SUBPIXELS_PER_AXIS = 8


def render_fractional_pixels(config, trial, *, pose, elapsed_s):
    """Render the virtual red disk with a fixed 8×8 edge-pixel coverage grid."""
    validate_pose(pose)
    cx_world, cy_world = sphere_center(config, trial, elapsed_s)
    dx, dy = cx_world - pose["x_m"], cy_world - pose["y_m"]
    distance = math.hypot(dx, dy)
    sphere_radius = config["virtual_sphere_radius_m"]
    if distance <= sphere_radius:
        raise LoomingScenarioError("virtual camera entered sphere")
    bearing = (math.atan2(dy, dx) - pose["heading_rad"] + math.pi) % (2 * math.pi) - math.pi
    width, height = config["image_width_px"], config["image_height_px"]
    half_fov = config["horizontal_fov_half_angle_rad"]
    pixels = [[(0, 0, 0) for _ in range(width)] for _ in range(height)]
    if abs(bearing) > half_fov:
        return tuple(tuple(row) for row in pixels)

    center_x = round((1 - bearing / half_fov) * (width - 1) / 2)
    center_y = height // 2
    radius = max(1.0, math.asin(sphere_radius / distance) / half_fov * (width - 1) / 2)
    lo_x = max(0, math.floor(center_x - radius - 0.5))
    hi_x = min(width - 1, math.ceil(center_x + radius + 0.5))
    lo_y = max(0, math.floor(center_y - radius - 0.5))
    hi_y = min(height - 1, math.ceil(center_y + radius + 0.5))
    radius_sq = radius * radius
    offsets = tuple((i + 0.5) / SUBPIXELS_PER_AXIS - 0.5 for i in range(SUBPIXELS_PER_AXIS))
    for y in range(lo_y, hi_y + 1):
        for x in range(lo_x, hi_x + 1):
            ax, ay = abs(x - center_x), abs(y - center_y)
            min_distance_sq = max(0.0, ax - 0.5) ** 2 + max(0.0, ay - 0.5) ** 2
            if min_distance_sq >= radius_sq:
                continue
            max_distance_sq = (ax + 0.5) ** 2 + (ay + 0.5) ** 2
            if max_distance_sq <= radius_sq:
                red = 255
            else:
                covered = sum(
                    (x + ox - center_x) ** 2 + (y + oy - center_y) ** 2 <= radius_sq
                    for ox in offsets for oy in offsets
                )
                red = round(255 * covered / (SUBPIXELS_PER_AXIS ** 2))
            pixels[y][x] = (red, 0, 0)
    return tuple(tuple(row) for row in pixels)


class FractionalRedTargetDetector:
    """Estimate fractional red target area and centroid from RGB intensity."""

    def detect(self, frame, *, timestamp_ns, frame_id, source_valid=True):
        if type(source_valid) is not bool:
            raise CameraTargetError("source_valid must be bool")
        if not source_valid:
            return neutral_perception_frame(timestamp_ns=timestamp_ns, frame_id=frame_id, valid=False)
        if not isinstance(frame, Sequence) or isinstance(frame, (str, bytes)) or not frame:
            raise CameraTargetError("frame must be a non-empty row sequence")
        width = None
        total_red = 0
        weighted_x = 0
        for row in frame:
            if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or not row:
                raise CameraTargetError("each frame row must be a non-empty pixel sequence")
            if width is None:
                width = len(row)
            elif len(row) != width:
                raise CameraTargetError("frame rows must have equal width")
            for x, pixel in enumerate(row):
                if (not isinstance(pixel, Sequence) or isinstance(pixel, (str, bytes)) or len(pixel) != 3
                        or any(type(channel) is not int or not 0 <= channel <= 255 for channel in pixel)):
                    raise CameraTargetError("pixels must be RGB integer triples in [0,255]")
                if pixel[1] == 0 and pixel[2] == 0:
                    total_red += pixel[0]
                    weighted_x += x * pixel[0]
        if total_red == 0:
            return neutral_perception_frame(timestamp_ns=timestamp_ns, frame_id=frame_id, valid=True)
        center_x = weighted_x / total_red
        target_x = 0.0 if width == 1 else 2 * center_x / (width - 1) - 1
        target_area = total_red / (255 * width * len(frame))
        return make_perception_frame(
            timestamp_ns=timestamp_ns, frame_id=frame_id,
            target_x=max(-1.0, min(1.0, target_x)), target_area=target_area,
            confidence=1.0, valid=True,
        )
