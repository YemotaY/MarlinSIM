"""Physics simulation — thermal model, stepper-to-position, endstop triggers."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from .models import PrinterModel, ThermalElementConfig

logger = logging.getLogger(__name__)


@dataclass
class ThermalState:
    """State of a single thermal element (hotend or bed)."""
    current_temp: float  # °C
    target_temp: float   # °C
    pwm_duty: int        # 0-255
    config: ThermalElementConfig
    ambient_temp: float

    def step(self, dt: float) -> None:
        """Advance thermal simulation by dt seconds.

        Simple first-order thermal model:
          dT/dt = (P_heater - P_loss) / C_thermal

        where:
          P_heater = pwm_duty/255 * heater_power_watts
          P_loss   = (T - T_ambient) * ambient_loss_w_per_k
          C_thermal = thermal_mass_j_per_k
        """
        duty_frac = self.pwm_duty / 255.0
        p_heater = duty_frac * self.config.heater_power_watts
        p_loss = (self.current_temp - self.ambient_temp) * self.config.ambient_loss_w_per_k
        dt_temp = (p_heater - p_loss) / self.config.thermal_mass_j_per_k
        self.current_temp += dt_temp * dt

        # Clamp to reasonable range
        self.current_temp = max(self.ambient_temp - 5.0, self.current_temp)
        self.current_temp = min(400.0, self.current_temp)  # safety cap


@dataclass
class AxisState:
    """State of a single motion axis."""
    position_steps: int = 0
    position_mm: float = 0.0
    steps_per_mm: float = 80.0
    min_pos: float = 0.0
    max_pos: float = 250.0
    home_pos: float = 0.0
    homed: bool = False
    endstop_triggered: bool = False
    endstop_side: str = "min"  # "min" or "max"

    def update_from_steps(self) -> None:
        """Recalculate mm position from step count."""
        self.position_mm = self.position_steps / self.steps_per_mm

    def check_endstop(self) -> bool:
        """Check if endstop would be triggered at current position."""
        if self.endstop_side == "min":
            self.endstop_triggered = self.position_mm <= self.min_pos
        else:
            self.endstop_triggered = self.position_mm >= self.max_pos
        return self.endstop_triggered


class PhysicsEngine:
    """Simulates the physical behavior of the 3D printer.

    Reads stepper positions and heater PWM from shared memory,
    computes thermal changes and endstop states, writes back
    temperature readings and endstop triggers.
    """

    def __init__(self, printer: PrinterModel):
        self.printer = printer
        self._last_update = time.monotonic()

        # Initialize axis states
        self.axes: dict[str, AxisState] = {}
        for name, ax_cfg in printer.axes.items():
            self.axes[name] = AxisState(
                steps_per_mm=ax_cfg.steps_per_mm,
                min_pos=ax_cfg.min_pos,
                max_pos=ax_cfg.max_pos,
                home_pos=ax_cfg.home_pos,
                endstop_side=ax_cfg.endstop,
            )

        # Extruder axis
        self.axes["E"] = AxisState(
            steps_per_mm=printer.extruder.steps_per_mm,
            min_pos=-999999.0,
            max_pos=999999.0,
        )

        # Initialize thermal states
        ambient = printer.thermal.ambient_temp
        self.hotend = ThermalState(
            current_temp=ambient,
            target_temp=0.0,
            pwm_duty=0,
            config=printer.thermal.hotend,
            ambient_temp=ambient,
        )
        self.bed = ThermalState(
            current_temp=ambient,
            target_temp=0.0,
            pwm_duty=0,
            config=printer.thermal.bed,
            ambient_temp=ambient,
        ) if printer.heated_bed_enabled else None

        # Encoder state
        self.encoder_position: int = 0
        self.encoder_button: bool = False

    def update(self, dt: Optional[float] = None) -> None:
        """Run one physics step.

        Args:
            dt: Time delta in seconds.  If None, computed from wall clock.
        """
        now = time.monotonic()
        if dt is None:
            dt = now - self._last_update
        self._last_update = now

        # Clamp dt to avoid explosion on lag spikes
        dt = min(dt, 0.5)

        # Update thermal
        self.hotend.step(dt)
        if self.bed:
            self.bed.step(dt)

        # Update axis positions from steps
        for ax in self.axes.values():
            ax.update_from_steps()
            ax.check_endstop()

    def set_stepper_positions(self, x: int, y: int, z: int, e: int) -> None:
        """Update stepper step counts from Marlin process."""
        if "X" in self.axes:
            self.axes["X"].position_steps = x
        if "Y" in self.axes:
            self.axes["Y"].position_steps = y
        if "Z" in self.axes:
            self.axes["Z"].position_steps = z
        if "E" in self.axes:
            self.axes["E"].position_steps = e

    def set_heater_pwm(self, hotend_pwm: int, bed_pwm: int) -> None:
        """Update heater PWM values from Marlin process."""
        self.hotend.pwm_duty = hotend_pwm
        if self.bed:
            self.bed.pwm_duty = bed_pwm

    def get_temperatures(self) -> tuple[float, float, float]:
        """Return (hotend_temp, bed_temp, ambient_temp)."""
        bed_temp = self.bed.current_temp if self.bed else self.printer.thermal.ambient_temp
        return (
            self.hotend.current_temp,
            bed_temp,
            self.printer.thermal.ambient_temp,
        )

    def get_positions_mm(self) -> dict[str, float]:
        """Return current axis positions in mm."""
        return {name: ax.position_mm for name, ax in self.axes.items()}

    def get_endstop_states(self) -> dict[str, bool]:
        """Return endstop trigger states."""
        return {name: ax.endstop_triggered for name, ax in self.axes.items()
                if name != "E"}

    def to_state_dict(self) -> dict:
        """Serialize full physics state for Web UI."""
        return {
            "axes": {
                name: {
                    "position_mm": round(ax.position_mm, 3),
                    "position_steps": ax.position_steps,
                    "homed": ax.homed,
                    "endstop": ax.endstop_triggered,
                }
                for name, ax in self.axes.items()
            },
            "thermal": {
                "hotend": {
                    "current": round(self.hotend.current_temp, 1),
                    "target": round(self.hotend.target_temp, 1),
                    "pwm": self.hotend.pwm_duty,
                },
                "bed": {
                    "current": round(self.bed.current_temp, 1) if self.bed else 0,
                    "target": round(self.bed.target_temp, 1) if self.bed else 0,
                    "pwm": self.bed.pwm_duty if self.bed else 0,
                },
                "ambient": self.printer.thermal.ambient_temp,
            },
            "encoder": {
                "position": self.encoder_position,
                "button": self.encoder_button,
            },
        }
