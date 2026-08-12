"""G-code analyzer — extracts layer geometry for animation frame generation.

Parses G-code line by line, tracks extruder position, and groups moves into
layers. Each layer records the line segments that were printed so that the
projector and rasterizer can build animation frames.

Memory-efficient: processes the file in a streaming fashion, only keeping
the segment list for completed layers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class Segment:
    """A single printed line segment in 3D space."""
    __slots__ = ("x0", "y0", "z0", "x1", "y1", "z1")
    x0: float
    y0: float
    z0: float
    x1: float
    y1: float
    z1: float


@dataclass
class Layer:
    """A collection of segments at a given Z height."""
    z_height: float
    start_line: int  # line number in original G-code where this layer starts
    segments: List[Segment] = field(default_factory=list)

    @property
    def segment_count(self) -> int:
        return len(self.segments)


# Regex for fast G-code parsing — pre-compiled for speed
_RE_G0G1 = re.compile(
    r"^G[01]\s"
    r"(?:.*?X(?P<x>-?[\d.]+))?"
    r"(?:.*?Y(?P<y>-?[\d.]+))?"
    r"(?:.*?Z(?P<z>-?[\d.]+))?"
    r"(?:.*?E(?P<e>-?[\d.]+))?"
    r"(?:.*?F(?P<f>-?[\d.]+))?",
    re.IGNORECASE,
)

_RE_LAYER_COMMENT = re.compile(
    r";\s*(?:LAYER:|layer:|LAYER_CHANGE|Z:)([\d.]+)?",
    re.IGNORECASE,
)


class GCodeAnalyzer:
    """Analyzes a G-code file and extracts per-layer geometry.

    After calling analyze(), access:
        .layers  — list of Layer objects
        .bounds  — (xmin, xmax, ymin, ymax, zmin, zmax) bounding box
    """

    def __init__(self):
        self.layers: List[Layer] = []
        self.bounds: Tuple[float, float, float, float, float, float] = (
            float("inf"), float("-inf"),
            float("inf"), float("-inf"),
            float("inf"), float("-inf"),
        )
        self._cur_x: float = 0.0
        self._cur_y: float = 0.0
        self._cur_z: float = 0.0
        self._cur_e: float = 0.0
        self._last_z: float = -1.0
        self._current_layer: Optional[Layer] = None

    def analyze(self, filepath: str) -> List[Layer]:
        """Parse G-code file and return list of layers with segments.

        Args:
            filepath: Path to .gcode file

        Returns:
            List of Layer objects with 3D segments
        """
        self.layers = []
        self._cur_x = 0.0
        self._cur_y = 0.0
        self._cur_z = 0.0
        self._cur_e = 0.0
        self._last_z = -1.0
        self._current_layer = None

        xmin = ymin = zmin = float("inf")
        xmax = ymax = zmax = float("-inf")

        with open(filepath, "r") as f:
            for line_no, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line or line.startswith(";"):
                    # Check for slicer layer comments to help detection
                    m = _RE_LAYER_COMMENT.match(line)
                    if m and m.group(1):
                        try:
                            z = float(m.group(1))
                            self._maybe_new_layer(z, line_no)
                        except ValueError:
                            pass
                    continue

                m = _RE_G0G1.match(line)
                if not m:
                    continue

                new_x = float(m.group("x")) if m.group("x") else self._cur_x
                new_y = float(m.group("y")) if m.group("y") else self._cur_y
                new_z = float(m.group("z")) if m.group("z") else self._cur_z
                new_e = float(m.group("e")) if m.group("e") else self._cur_e

                # Detect layer change by Z movement
                if new_z != self._cur_z:
                    self._maybe_new_layer(new_z, line_no)

                # Only record segments where extrusion happens (E increases)
                is_extrusion = new_e > self._cur_e

                if is_extrusion and self._current_layer is not None:
                    seg = Segment(
                        self._cur_x, self._cur_y, self._cur_z,
                        new_x, new_y, new_z,
                    )
                    self._current_layer.segments.append(seg)

                    # Update bounds
                    for x in (self._cur_x, new_x):
                        if x < xmin:
                            xmin = x
                        if x > xmax:
                            xmax = x
                    for y in (self._cur_y, new_y):
                        if y < ymin:
                            ymin = y
                        if y > ymax:
                            ymax = y
                    for z in (self._cur_z, new_z):
                        if z < zmin:
                            zmin = z
                        if z > zmax:
                            zmax = z

                self._cur_x = new_x
                self._cur_y = new_y
                self._cur_z = new_z
                self._cur_e = new_e

        # Finalize last layer
        if self._current_layer and self._current_layer.segments:
            self.layers.append(self._current_layer)

        # Safety: if no layers found, create a dummy
        if not self.layers:
            self.layers.append(Layer(z_height=0.0, start_line=1))

        # Fix bounds if nothing was found
        if xmin == float("inf"):
            xmin = xmax = ymin = ymax = zmin = zmax = 0.0

        self.bounds = (xmin, xmax, ymin, ymax, zmin, zmax)
        return self.layers

    def _maybe_new_layer(self, z: float, line_no: int):
        """Start a new layer if Z has changed significantly."""
        if abs(z - self._last_z) < 0.001:
            return

        # Save current layer if it has segments
        if self._current_layer and self._current_layer.segments:
            self.layers.append(self._current_layer)

        self._current_layer = Layer(z_height=z, start_line=line_no)
        self._last_z = z
        self._cur_z = z
