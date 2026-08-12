"""Ender 3 V2 printer profile — SKR Mini E3 V2 + ST7920 128x64 display."""

from .base import PrinterProfile


class Ender3V2Profile(PrinterProfile):
    """Profile for Creality Ender 3 V2 with stock or SKR Mini E3 V2 board.

    Display: ST7920 compatible 128x64 monochrome LCD
    Board: SKR Mini E3 V2 (STM32F103RCT6, 20KB RAM, 256KB Flash)
    Build volume: 220 x 220 x 250 mm
    """

    def __init__(self):
        super().__init__(
            name="ender3v2",
            description="Ender 3 V2 / SKR Mini E3 V2 — ST7920 128x64",
            display_width=128,
            display_height=64,
            display_type="st7920",
            build_volume_x=220.0,
            build_volume_y=220.0,
            build_volume_z=250.0,
            max_frame_bytes=120,
            supports_grayscale=False,
        )
