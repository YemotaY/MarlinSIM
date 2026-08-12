"""Simulator core — orchestrates the Marlin process, physics, SHM IPC, and display."""

from __future__ import annotations

import asyncio
import logging
import os
import pty
import signal
import struct
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from .builder import MarlinBuilder
from .models import PrinterModel, load_model
from .physics import PhysicsEngine
from .shm_client import ShmClient

logger = logging.getLogger(__name__)

# Physics update rate
PHYSICS_HZ = 20  # 20 Hz = 50ms interval


class SimulatorCore:
    """Main simulation engine.

    Lifecycle:
      1. __init__(model, marlin_version)
      2. await start()        — build Marlin (if needed), launch process, init SHM
      3. await run()           — main simulation loop (physics + IPC)
      4. await stop()          — kill Marlin process, cleanup

    IPC architecture:
      - Marlin runs as a native Linux process (compiled with linux_native HAL)
      - Communication via POSIX shared memory (/dev/shm/marlinsim_shm)
      - Serial I/O via PTY (pseudo-terminal) for G-code commands
      - Python physics engine reads stepper positions, computes temperatures,
        writes them back for Marlin to read
    """

    def __init__(
        self,
        printer: PrinterModel | str,
        marlin_version: str = "2.1.x",
        workspace: Optional[Path] = None,
        skip_build: bool = False,
    ):
        if isinstance(printer, str):
            printer = load_model(printer)
        self.printer = printer
        self.marlin_version = marlin_version
        self.skip_build = skip_build

        self.builder = MarlinBuilder(
            printer=printer,
            marlin_version=marlin_version,
            workspace=workspace,
        )

        self.physics = PhysicsEngine(printer)
        self.shm = ShmClient(create=True)

        self._process: Optional[subprocess.Popen] = None
        self._pty_master: int = -1
        self._pty_slave: int = -1
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

        # Callbacks for external consumers (Web UI)
        self._on_lcd_update: Optional[Callable[[bytes], None]] = None
        self._on_state_update: Optional[Callable[[dict], None]] = None
        self._gcode_log: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Build Marlin (if needed), initialize SHM, launch process."""
        logger.info("Starting simulator for %s ...", self.printer.name)

        # 1. Build Marlin
        if not self.skip_build:
            await asyncio.get_event_loop().run_in_executor(
                None, self._build_marlin
            )

        # 2. Initialize shared memory
        lcd_w = self.printer.display.width
        lcd_h = self.printer.display.height
        self.shm.open(lcd_w=lcd_w, lcd_h=lcd_h)

        # Write initial temperatures
        ambient = self.printer.thermal.ambient_temp
        self.shm.write_temperatures(ambient, ambient, ambient, ambient)

        # 3. Create PTY for serial communication
        self._pty_master, self._pty_slave = pty.openpty()
        pty_name = os.ttyname(self._pty_slave)
        logger.info("PTY created: %s", pty_name)

        # 4. Launch Marlin process
        exe = self.builder.get_executable()
        logger.info("Launching Marlin: %s", exe)

        env = os.environ.copy()
        env["MARLIN_SIM_PTY"] = pty_name

        self._process = subprocess.Popen(
            [str(exe)],
            stdin=self._pty_slave,
            stdout=self._pty_slave,
            stderr=subprocess.PIPE,
            env=env,
            preexec_fn=os.setsid,
        )

        self._running = True
        logger.info("Marlin process started (PID %d)", self._process.pid)

    async def run(self) -> None:
        """Main simulation loop — runs until stop() is called."""
        self._loop_task = asyncio.current_task()

        physics_interval = 1.0 / PHYSICS_HZ
        lcd_fb_size = (self.printer.display.width * self.printer.display.height) // 8

        try:
            while self._running:
                loop_start = time.monotonic()

                # Check if Marlin process is still alive
                if self._process and self._process.poll() is not None:
                    logger.warning(
                        "Marlin process exited with code %d",
                        self._process.returncode,
                    )
                    self._running = False
                    break

                # Read heater PWM from SHM (written by Marlin)
                hotend_pwm, bed_pwm = self.shm.read_heater_pwm()
                self.physics.set_heater_pwm(hotend_pwm, bed_pwm)

                # Read stepper positions from SHM (written by Marlin)
                x, y, z, e = self.shm.read_stepper_pos()
                self.physics.set_stepper_positions(x, y, z, e)

                # Step physics
                self.physics.update(physics_interval)

                # Write temperatures back to SHM
                ht, bt, at = self.physics.get_temperatures()
                self.shm.write_temperatures(ht, 0.0, bt, at)

                # Write endstop states
                endstops = self.physics.get_endstop_states()
                self.shm.write_endstops(
                    x_min=endstops.get("X", False),
                    x_max=False,
                    y_min=endstops.get("Y", False),
                    y_max=False,
                    z_min=endstops.get("Z", False),
                    z_max=False,
                )

                # Check LCD update
                if self.shm.is_lcd_dirty():
                    lcd_data = self.shm.read_lcd(lcd_fb_size)
                    self.shm.clear_lcd_dirty()
                    if self._on_lcd_update:
                        self._on_lcd_update(lcd_data)

                # Notify state update
                if self._on_state_update:
                    self._on_state_update(self.physics.to_state_dict())

                # Sleep remaining interval
                elapsed = time.monotonic() - loop_start
                sleep_time = physics_interval - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                else:
                    await asyncio.sleep(0)  # yield to event loop

        except asyncio.CancelledError:
            logger.info("Simulation loop cancelled.")
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the simulation and clean up."""
        logger.info("Stopping simulator ...")
        self._running = False

        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        # Kill Marlin process
        if self._process and self._process.poll() is None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                    self._process.wait(timeout=2)
            except ProcessLookupError:
                pass
            logger.info("Marlin process terminated.")

        # Close PTY
        if self._pty_master >= 0:
            os.close(self._pty_master)
            self._pty_master = -1
        if self._pty_slave >= 0:
            os.close(self._pty_slave)
            self._pty_slave = -1

        # Close SHM
        self.shm.close()

        logger.info("Simulator stopped.")

    # ------------------------------------------------------------------
    # G-code interface
    # ------------------------------------------------------------------

    def send_gcode(self, line: str) -> None:
        """Send a G-code command to Marlin via PTY."""
        if self._pty_master < 0:
            logger.warning("PTY not open — cannot send G-code")
            return

        if not line.endswith("\n"):
            line += "\n"

        os.write(self._pty_master, line.encode("ascii", errors="replace"))
        self._gcode_log.append(f"> {line.strip()}")
        logger.debug("Sent G-code: %s", line.strip())

    async def read_response(self, timeout: float = 2.0) -> list[str]:
        """Read response lines from Marlin via PTY."""
        lines = []
        deadline = time.monotonic() + timeout

        loop = asyncio.get_event_loop()

        while time.monotonic() < deadline:
            try:
                data = await asyncio.wait_for(
                    loop.run_in_executor(None, self._pty_read_nonblock),
                    timeout=0.1,
                )
                if data:
                    text = data.decode("ascii", errors="replace")
                    for line in text.splitlines():
                        line = line.strip()
                        if line:
                            lines.append(line)
                            self._gcode_log.append(f"< {line}")
                    if any("ok" in l.lower() for l in lines):
                        break
            except (asyncio.TimeoutError, OSError):
                break

        return lines

    def _pty_read_nonblock(self) -> bytes:
        """Non-blocking read from PTY master."""
        import select
        r, _, _ = select.select([self._pty_master], [], [], 0.05)
        if r:
            return os.read(self._pty_master, 4096)
        return b""

    # ------------------------------------------------------------------
    # Encoder interaction
    # ------------------------------------------------------------------

    def encoder_rotate(self, clicks: int) -> None:
        """Simulate encoder rotation (positive = clockwise)."""
        steps = clicks * self.printer.display.encoder_steps_per_click
        self.physics.encoder_position += steps
        self.shm.write_encoder(self.physics.encoder_position, self.physics.encoder_button)

    def encoder_click(self, pressed: bool = True) -> None:
        """Simulate encoder button press/release."""
        self.physics.encoder_button = pressed
        self.shm.write_encoder(self.physics.encoder_position, pressed)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def on_lcd_update(self, callback: Callable[[bytes], None]) -> None:
        """Register callback for LCD framebuffer updates."""
        self._on_lcd_update = callback

    def on_state_update(self, callback: Callable[[dict], None]) -> None:
        """Register callback for physics state updates."""
        self._on_state_update = callback

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def get_lcd_framebuffer(self) -> bytes:
        """Get current LCD framebuffer contents."""
        fb_size = (self.printer.display.width * self.printer.display.height) // 8
        return self.shm.read_lcd(fb_size)

    def get_state(self) -> dict:
        """Get full simulator state."""
        return {
            "running": self._running,
            "printer": self.printer.name,
            "marlin_version": self.marlin_version,
            "marlin_pid": self._process.pid if self._process else None,
            "physics": self.physics.to_state_dict(),
        }

    def get_gcode_log(self, last_n: int = 50) -> list[str]:
        """Get recent G-code communication log."""
        return self._gcode_log[-last_n:]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_marlin(self) -> None:
        """Synchronous build sequence."""
        self.builder.clone()
        self.builder.configure()
        self.builder.build()
