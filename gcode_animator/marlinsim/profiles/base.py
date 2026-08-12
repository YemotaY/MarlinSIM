"""Base class for printer display profiles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PrinterProfile:
    """Base printer display profile.

    Defines the display resolution and other parameters that the animation
    generator needs to know to produce correctly-sized frames.
    """
    name: str
    description: str
    display_width: int
    display_height: int
    display_type: str  # "st7920", "ssd1306", "dwin", etc.
    build_volume_x: float  # mm
    build_volume_y: float  # mm
    build_volume_z: float  # mm
    max_frame_bytes: int = 120  # max compressed frame size in bytes
    supports_grayscale: bool = False
