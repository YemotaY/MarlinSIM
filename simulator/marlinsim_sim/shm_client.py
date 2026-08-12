"""Shared-memory IPC client — reads/writes the SHM segment created by the Marlin process."""

from __future__ import annotations

import ctypes
import logging
import mmap
import os
import struct
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Must match sim_bridge.h constants
SIM_SHM_NAME = "/marlinsim_shm"
SIM_SHM_SIZE = 8192

SHM_OFF_MAGIC = 0
SHM_OFF_VERSION = 4
SHM_OFF_FLAGS = 8
SHM_OFF_LCD_W = 16
SHM_OFF_LCD_H = 18
SHM_OFF_LCD_DATA = 64
SHM_OFF_STEPPER = 4160
SHM_OFF_TEMP = 4176
SHM_OFF_ENDSTOP = 4192
SHM_OFF_ENCODER = 4200
SHM_OFF_HEATER_PWM = 4208

SIM_FLAG_RUNNING = 1 << 0
SIM_FLAG_LCD_DIRTY = 1 << 1
SIM_FLAG_KILL = 1 << 2
SIM_FLAG_ENCODER_CLICK = 1 << 3


class ShmClient:
    """Python-side shared memory client for communicating with the Marlin process.

    The Marlin process (C++) creates and owns the SHM segment via sim_bridge.
    This client opens it and provides typed read/write accessors.

    Alternatively, if Marlin hasn't created the SHM yet, this client can
    create it (useful when Python starts first and Marlin connects later).
    """

    def __init__(self, create: bool = True):
        self._mm: Optional[mmap.mmap] = None
        self._fd: int = -1
        self._create = create

    def open(self, lcd_w: int = 128, lcd_h: int = 64) -> bool:
        """Open or create the shared memory segment."""
        shm_path = Path("/dev/shm") / SIM_SHM_NAME.lstrip("/")

        if self._create:
            # Create the segment ourselves
            fd = os.open(str(shm_path), os.O_CREAT | os.O_RDWR, 0o666)
            os.ftruncate(fd, SIM_SHM_SIZE)
        else:
            # Wait for Marlin to create it
            for _ in range(50):  # 5 seconds
                if shm_path.exists():
                    break
                time.sleep(0.1)
            if not shm_path.exists():
                logger.error("SHM not found at %s", shm_path)
                return False
            fd = os.open(str(shm_path), os.O_RDWR)

        self._fd = fd
        self._mm = mmap.mmap(fd, SIM_SHM_SIZE)

        if self._create:
            # Initialize header
            self._mm[SHM_OFF_MAGIC:SHM_OFF_MAGIC + 4] = b"MSIM"
            struct.pack_into("<I", self._mm, SHM_OFF_VERSION, 1)
            struct.pack_into("<H", self._mm, SHM_OFF_LCD_W, lcd_w)
            struct.pack_into("<H", self._mm, SHM_OFF_LCD_H, lcd_h)
            self._set_flag(SIM_FLAG_RUNNING)

            # Initialize temperatures to ambient
            for ch in range(4):
                struct.pack_into("<f", self._mm, SHM_OFF_TEMP + ch * 4, 22.0)

        logger.info("SHM client opened: %s (%d bytes)", shm_path, SIM_SHM_SIZE)
        return True

    def close(self) -> None:
        """Close and unlink the shared memory."""
        if self._mm:
            self._clear_flag(SIM_FLAG_RUNNING)
            self._mm.close()
            self._mm = None
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
        # Clean up if we created it
        if self._create:
            shm_path = Path("/dev/shm") / SIM_SHM_NAME.lstrip("/")
            if shm_path.exists():
                shm_path.unlink()

    def is_open(self) -> bool:
        return self._mm is not None

    # ------------------------------------------------------------------
    # LCD framebuffer
    # ------------------------------------------------------------------

    def read_lcd(self, size: int) -> bytes:
        """Read the LCD framebuffer data."""
        if not self._mm:
            return b""
        return bytes(self._mm[SHM_OFF_LCD_DATA:SHM_OFF_LCD_DATA + size])

    def is_lcd_dirty(self) -> bool:
        """Check if Marlin has written new LCD data."""
        return self._test_flag(SIM_FLAG_LCD_DIRTY)

    def clear_lcd_dirty(self) -> None:
        """Clear the LCD dirty flag after reading."""
        self._clear_flag(SIM_FLAG_LCD_DIRTY)

    # ------------------------------------------------------------------
    # Stepper positions
    # ------------------------------------------------------------------

    def read_stepper_pos(self) -> tuple[int, int, int, int]:
        """Read stepper positions (X, Y, Z, E) as step counts."""
        if not self._mm:
            return (0, 0, 0, 0)
        x, y, z, e = struct.unpack_from("<iiii", self._mm, SHM_OFF_STEPPER)
        return (x, y, z, e)

    def write_stepper_pos(self, x: int, y: int, z: int, e: int) -> None:
        """Write stepper positions (for host-controlled positioning)."""
        if not self._mm:
            return
        struct.pack_into("<iiii", self._mm, SHM_OFF_STEPPER, x, y, z, e)

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    def write_temperatures(
        self, hotend0: float, hotend1: float, bed: float, ambient: float
    ) -> None:
        """Write simulated temperature readings for Marlin to read."""
        if not self._mm:
            return
        struct.pack_into("<ffff", self._mm, SHM_OFF_TEMP,
                         hotend0, hotend1, bed, ambient)

    def read_heater_pwm(self) -> tuple[int, int]:
        """Read heater PWM duty cycles written by Marlin."""
        if not self._mm:
            return (0, 0)
        return (self._mm[SHM_OFF_HEATER_PWM], self._mm[SHM_OFF_HEATER_PWM + 1])

    # ------------------------------------------------------------------
    # Endstops
    # ------------------------------------------------------------------

    def write_endstops(
        self,
        x_min: bool, x_max: bool,
        y_min: bool, y_max: bool,
        z_min: bool, z_max: bool,
    ) -> None:
        """Write endstop states for Marlin to read."""
        if not self._mm:
            return
        states = [x_min, x_max, y_min, y_max, z_min, z_max]
        for i, s in enumerate(states):
            self._mm[SHM_OFF_ENDSTOP + i] = 1 if s else 0

    # ------------------------------------------------------------------
    # Encoder
    # ------------------------------------------------------------------

    def write_encoder(self, position: int, button: bool) -> None:
        """Write encoder state for Marlin to read."""
        if not self._mm:
            return
        struct.pack_into("<i", self._mm, SHM_OFF_ENCODER, position)
        if button:
            self._set_flag(SIM_FLAG_ENCODER_CLICK)
        else:
            self._clear_flag(SIM_FLAG_ENCODER_CLICK)

    # ------------------------------------------------------------------
    # Flags
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._test_flag(SIM_FLAG_RUNNING)

    def request_kill(self) -> None:
        self._set_flag(SIM_FLAG_KILL)

    def _set_flag(self, flag: int) -> None:
        if not self._mm:
            return
        flags = struct.unpack_from("<I", self._mm, SHM_OFF_FLAGS)[0]
        flags |= flag
        struct.pack_into("<I", self._mm, SHM_OFF_FLAGS, flags)

    def _clear_flag(self, flag: int) -> None:
        if not self._mm:
            return
        flags = struct.unpack_from("<I", self._mm, SHM_OFF_FLAGS)[0]
        flags &= ~flag
        struct.pack_into("<I", self._mm, SHM_OFF_FLAGS, flags)

    def _test_flag(self, flag: int) -> bool:
        if not self._mm:
            return False
        flags = struct.unpack_from("<I", self._mm, SHM_OFF_FLAGS)[0]
        return (flags & flag) != 0
