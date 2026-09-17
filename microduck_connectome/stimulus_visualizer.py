"""Dependency-free JSONL/SVG stimulus trace visualizer for P4-05."""

from collections.abc import Mapping
import json
import math

from .perception_frame import make_perception_frame

STIMULUS_CHANNELS = ("lc10a_left", "lc10a_right", "lplc2_left", "lplc2_right")


class StimulusVisualizerError(ValueError):
    """Stimulus trace data violates the P4-05 contract."""


def _bounded(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StimulusVisualizerError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise StimulusVisualizerError(f"{label} must be finite in [0,1]")
    return value


class StimulusTrace:
    """Collect validated perception/stimulus samples and export inspectable traces."""

    def __init__(self):
        self._records = []

    def append(self, frame, channels):
        if not isinstance(frame, Mapping):
            raise StimulusVisualizerError("frame must be a mapping")
        try:
            canonical = make_perception_frame(**dict(frame))
        except (TypeError, ValueError) as error:
            raise StimulusVisualizerError("frame violates frozen perception contract") from error
        if not isinstance(channels, Mapping) or set(channels) != set(STIMULUS_CHANNELS):
            raise StimulusVisualizerError("channels must contain exactly the four Phase-4 stimulus names")
        normalized = {
            name: _bounded(channels[name], name)
            for name in STIMULUS_CHANNELS
        }
        if self._records:
            previous = self._records[-1]["frame"]
            if canonical["timestamp_ns"] <= previous["timestamp_ns"]:
                raise StimulusVisualizerError("trace timestamps must increase strictly")
            if canonical["frame_id"] <= previous["frame_id"]:
                raise StimulusVisualizerError("trace frame_id values must increase strictly")
        self._records.append({"frame": canonical, "channels": normalized})

    def records(self):
        return [
            {
                "frame": dict(record["frame"]),
                "channels": dict(record["channels"]),
            }
            for record in self._records
        ]

    def to_jsonl(self):
        return "\n".join(
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            for record in self._records
        ) + ("\n" if self._records else "")

    def to_svg(self, *, width=800, height=440):
        if not self._records:
            raise StimulusVisualizerError("cannot render an empty trace")
        if type(width) is not int or width < 320:
            raise StimulusVisualizerError("width must be an integer >= 320")
        if type(height) is not int or height < 240:
            raise StimulusVisualizerError("height must be an integer >= 240")

        left = 130.0
        right = 20.0
        top = 20.0
        bottom = 20.0
        plot_width = width - left - right
        lane_height = (height - top - bottom) / len(STIMULUS_CHANNELS)
        first_ts = self._records[0]["frame"]["timestamp_ns"]
        last_ts = self._records[-1]["frame"]["timestamp_ns"]
        span = max(1, last_ts - first_ts)
        dash_patterns = ("none", "8 4", "3 3", "10 3 2 3")

        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect x="0" y="0" width="100%" height="100%" fill="white"/>',
            '<g fill="none" stroke="black" stroke-width="1">',
        ]
        for lane, name in enumerate(STIMULUS_CHANNELS):
            lane_top = top + lane * lane_height
            y_high = lane_top + 8.0
            y_low = lane_top + lane_height - 8.0
            parts.append(
                f'<line x1="{left:.2f}" y1="{y_low:.2f}" x2="{width-right:.2f}" y2="{y_low:.2f}" stroke-dasharray="2 4"/>'
            )
            points = []
            for record in self._records:
                timestamp = record["frame"]["timestamp_ns"]
                x = left + ((timestamp - first_ts) / span) * plot_width
                value = record["channels"][name]
                y = y_low - value * (y_low - y_high)
                points.append(f"{x:.2f},{y:.2f}")
            dash = dash_patterns[lane]
            dash_attr = "" if dash == "none" else f' stroke-dasharray="{dash}"'
            parts.append(f'<polyline points="{" ".join(points)}" stroke="black" stroke-width="2"{dash_attr}/>')
            parts.append(
                f'<text x="8" y="{lane_top + lane_height/2:.2f}" fill="black" stroke="none" font-size="12">{name}</text>'
            )
            parts.append(
                f'<text x="{left-28:.2f}" y="{y_high+4:.2f}" fill="black" stroke="none" font-size="10">1</text>'
            )
            parts.append(
                f'<text x="{left-28:.2f}" y="{y_low+4:.2f}" fill="black" stroke="none" font-size="10">0</text>'
            )
        parts.append("</g>")
        parts.append(
            f'<text x="{left:.2f}" y="{height-4:.2f}" fill="black" font-size="10">time: {first_ts}..{last_ts} ns</text>'
        )
        parts.append("</svg>")
        return "\n".join(parts) + "\n"
