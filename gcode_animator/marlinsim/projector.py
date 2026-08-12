"""Isometric projection — transforms 3D print segments to 2D screen space.

Uses a cabinet/isometric projection to render a simplified 3D view of the
print progress. The projection is designed to give a pleasing angled view
showing both the top surface and one or two sides of the print.

The projection fits the entire build volume into the target display resolution
with appropriate margins.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from .analyzer import Layer, Segment


@dataclass
class Segment2D:
    """A projected line segment in 2D screen space (integer pixels)."""
    __slots__ = ("x0", "y0", "x1", "y1", "depth")
    x0: int
    y0: int
    x1: int
    y1: int
    depth: float  # for painter's algorithm sorting


class IsometricProjector:
    """Projects 3D layer geometry onto a 2D display using isometric projection.

    The projection uses a fixed rotation around the vertical axis and a tilt
    angle to show the print from an angled top-down view. This gives a good
    visual impression of print progress with minimal computation.

    Args:
        bounds: (xmin, xmax, ymin, ymax, zmin, zmax) — model bounding box
        display_width: Target pixel width
        display_height: Target pixel height
        rotation_deg: Rotation angle for isometric view (degrees)
    """

    def __init__(
        self,
        bounds: Tuple[float, float, float, float, float, float],
        display_width: int = 128,
        display_height: int = 64,
        rotation_deg: float = 35.264,
    ):
        self.display_width = display_width
        self.display_height = display_height

        xmin, xmax, ymin, ymax, zmin, zmax = bounds

        # Center of model
        self._cx = (xmin + xmax) / 2.0
        self._cy = (ymin + ymax) / 2.0
        self._cz = (zmin + zmax) / 2.0

        # Model dimensions
        dx = max(xmax - xmin, 1.0)
        dy = max(ymax - ymin, 1.0)
        dz = max(zmax - zmin, 1.0)

        # Pre-compute rotation matrix (rotation around Z axis then tilt)
        rot_rad = math.radians(rotation_deg)
        tilt_rad = math.radians(30.0)  # tilt angle for top-down view

        cos_r = math.cos(rot_rad)
        sin_r = math.sin(rot_rad)
        cos_t = math.cos(tilt_rad)
        sin_t = math.sin(tilt_rad)

        # Combined rotation: first rotate around Z, then tilt around X
        # This gives an isometric-like projection
        self._m00 = cos_r
        self._m01 = sin_r
        self._m10 = -sin_r * cos_t
        self._m11 = cos_r * cos_t
        self._m12 = sin_t
        # Depth component for painter's algorithm
        self._d0 = sin_r * sin_t
        self._d1 = -cos_r * sin_t
        self._d2 = cos_t

        # Calculate scale to fit model in display with 4px margin
        margin = 4
        eff_w = display_width - 2 * margin
        eff_h = display_height - 2 * margin

        # Project bounding box corners to find screen extents
        corners = [
            (xmin, ymin, zmin), (xmax, ymin, zmin),
            (xmin, ymax, zmin), (xmax, ymax, zmin),
            (xmin, ymin, zmax), (xmax, ymin, zmax),
            (xmin, ymax, zmax), (xmax, ymax, zmax),
        ]
        sx_vals = []
        sy_vals = []
        for cx, cy, cz in corners:
            sx, sy, _ = self._project_raw(cx, cy, cz)
            sx_vals.append(sx)
            sy_vals.append(sy)

        raw_w = max(sx_vals) - min(sx_vals)
        raw_h = max(sy_vals) - min(sy_vals)

        if raw_w < 0.001:
            raw_w = 1.0
        if raw_h < 0.001:
            raw_h = 1.0

        self._scale = min(eff_w / raw_w, eff_h / raw_h)

        # Offset to center on screen
        mid_sx = (min(sx_vals) + max(sx_vals)) / 2.0
        mid_sy = (min(sy_vals) + max(sy_vals)) / 2.0
        self._ox = display_width / 2.0 - mid_sx * self._scale
        self._oy = display_height / 2.0 - mid_sy * self._scale

    def _project_raw(
        self, x: float, y: float, z: float
    ) -> Tuple[float, float, float]:
        """Raw projection without scale/offset — used for bounding box calc."""
        rx = x - self._cx
        ry = y - self._cy
        rz = z - self._cz

        sx = self._m00 * rx + self._m01 * ry
        sy = self._m10 * rx + self._m11 * ry + self._m12 * rz
        depth = self._d0 * rx + self._d1 * ry + self._d2 * rz

        return sx, -sy, depth  # flip Y for screen coordinates

    def project_point(
        self, x: float, y: float, z: float
    ) -> Tuple[int, int, float]:
        """Project a 3D point to screen pixel coordinates.

        Returns:
            (screen_x, screen_y, depth) — depth for sorting
        """
        sx, sy, depth = self._project_raw(x, y, z)
        px = int(sx * self._scale + self._ox + 0.5)
        py = int(sy * self._scale + self._oy + 0.5)
        return px, py, depth

    def project_layers(
        self,
        layers: List[Layer],
        from_layer: int,
        to_layer: int,
    ) -> List[Segment2D]:
        """Project multiple layers of 3D segments to 2D.

        Projects all segments in layers[from_layer:to_layer].

        Args:
            layers: List of Layer objects from the analyzer
            from_layer: Start layer index (inclusive)
            to_layer: End layer index (exclusive)

        Returns:
            List of Segment2D in screen space, sorted by depth (far first)
        """
        result: List[Segment2D] = []
        w = self.display_width
        h = self.display_height

        for layer in layers[from_layer:to_layer]:
            for seg in layer.segments:
                x0, y0, d0 = self.project_point(seg.x0, seg.y0, seg.z0)
                x1, y1, d1 = self.project_point(seg.x1, seg.y1, seg.z1)

                # Clip to display bounds (rough — full clipping in rasterizer)
                if (x0 < 0 and x1 < 0) or (x0 >= w and x1 >= w):
                    continue
                if (y0 < 0 and y1 < 0) or (y0 >= h and y1 >= h):
                    continue

                result.append(Segment2D(
                    x0=x0, y0=y0,
                    x1=x1, y1=y1,
                    depth=(d0 + d1) / 2.0,
                ))

        # Sort by depth — far segments first (painter's algorithm)
        result.sort(key=lambda s: s.depth)
        return result
