"""Rasterizer — converts 2D line segments to a 1-bit bitmap.

Uses Bresenham's line algorithm for fast integer-only rasterization.
Produces a packed 1-bit bitmap (MSB first, row-major) suitable for
direct compression and display on monochrome LCDs.
"""

from __future__ import annotations

from typing import List

from .projector import Segment2D


class Rasterizer:
    """Rasterizes 2D line segments onto a 1-bit bitmap.

    The bitmap is stored as a bytearray in row-major order, MSB-first packing.
    Each row is ceil(width/8) bytes wide.

    Args:
        width: Display width in pixels
        height: Display height in pixels
    """

    def __init__(self, width: int = 128, height: int = 64):
        self.width = width
        self.height = height
        self.row_bytes = (width + 7) // 8

    def rasterize(self, segments: List[Segment2D]) -> bytearray:
        """Rasterize a list of 2D segments into a 1-bit bitmap.

        Args:
            segments: List of Segment2D objects (already projected)

        Returns:
            bytearray of size row_bytes * height — packed 1-bit bitmap
        """
        w = self.width
        h = self.height
        rb = self.row_bytes
        buf = bytearray(rb * h)

        for seg in segments:
            self._draw_line(buf, seg.x0, seg.y0, seg.x1, seg.y1, w, h, rb)

        return buf

    @staticmethod
    def _draw_line(
        buf: bytearray,
        x0: int, y0: int, x1: int, y1: int,
        w: int, h: int, rb: int,
    ):
        """Bresenham's line algorithm — sets pixels in packed bitmap.

        Clips to display bounds. Optimized for minimal overhead.
        """
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy

        while True:
            # Set pixel if within bounds
            if 0 <= x0 < w and 0 <= y0 < h:
                byte_idx = y0 * rb + (x0 >> 3)
                bit_mask = 0x80 >> (x0 & 7)
                buf[byte_idx] |= bit_mask

            if x0 == x1 and y0 == y1:
                break

            e2 = 2 * err
            if e2 >= dy:
                if x0 == x1:
                    break
                err += dy
                x0 += sx
            if e2 <= dx:
                if y0 == y1:
                    break
                err += dx
                y0 += sy

    def clear(self) -> bytearray:
        """Return an empty (all-zero) bitmap."""
        return bytearray(self.row_bytes * self.height)

    def bitmap_to_text(self, bitmap: bytearray) -> str:
        """Debug: convert bitmap to ASCII art for terminal preview."""
        lines = []
        rb = self.row_bytes
        for y in range(self.height):
            row = ""
            for x in range(self.width):
                byte_idx = y * rb + (x >> 3)
                bit_mask = 0x80 >> (x & 7)
                row += "█" if (bitmap[byte_idx] & bit_mask) else " "
            lines.append(row)
        return "\n".join(lines)
