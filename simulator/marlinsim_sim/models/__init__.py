"""Printer model loader — loads JSON-based printer/board/display profiles."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent


@dataclass
class AxisConfig:
    """Single axis configuration."""
    min_pos: float
    max_pos: float
    home_pos: float
    home_dir: int
    steps_per_mm: float
    max_feedrate: float
    max_accel: float
    endstop: str  # "min" or "max"


@dataclass
class BoardConfig:
    """Mainboard configuration."""
    name: str
    mcu: str
    platformio_env: str
    marlin_board: str
    ram_kb: int
    flash_kb: int
    clock_mhz: int


@dataclass
class DisplayConfig:
    """Display hardware configuration."""
    type: str  # "st7920", "ssd1306", "dwin", etc.
    driver: str
    width: int
    height: int
    color_depth: int  # bits per pixel
    interface: str  # "spi", "i2c", "serial"
    encoder: bool
    encoder_steps_per_click: int
    beeper: bool
    marlin_defines: list[str] = field(default_factory=list)


@dataclass
class ExtruderConfig:
    """Extruder configuration."""
    count: int
    steps_per_mm: float
    max_feedrate: float
    max_accel: float
    nozzle_diameter: float
    filament_diameter: float
    max_temp: int
    min_extrude_temp: int


@dataclass
class ThermalElementConfig:
    """Single thermal element (hotend or bed)."""
    thermistor: int
    pid_p: float
    pid_i: float
    pid_d: float
    heater_power_watts: float
    thermal_mass_j_per_k: float
    ambient_loss_w_per_k: float


@dataclass
class ThermalConfig:
    """Thermal simulation parameters."""
    hotend: ThermalElementConfig
    bed: ThermalElementConfig
    ambient_temp: float


@dataclass
class PrinterModel:
    """Complete printer model for simulation."""
    name: str
    description: str
    board: BoardConfig
    display: DisplayConfig
    kinematics_type: str  # "cartesian", "corexy", "delta"
    axes: dict[str, AxisConfig]
    extruder: ExtruderConfig
    heated_bed_enabled: bool
    thermal: ThermalConfig
    build_volume: tuple[float, float, float]
    features: dict[str, bool]
    _source_path: Path | None = None

    @staticmethod
    def from_json(path: Path) -> "PrinterModel":
        """Load a printer model from a JSON file."""
        with open(path) as f:
            data = json.load(f)

        board = BoardConfig(**data["board"])

        disp_data = data["display"]
        display = DisplayConfig(
            type=disp_data["type"],
            driver=disp_data["driver"],
            width=disp_data["width"],
            height=disp_data["height"],
            color_depth=disp_data["color_depth"],
            interface=disp_data["interface"],
            encoder=disp_data.get("encoder", False),
            encoder_steps_per_click=disp_data.get("encoder_steps_per_click", 4),
            beeper=disp_data.get("beeper", False),
            marlin_defines=disp_data.get("marlin_defines", []),
        )

        axes = {}
        for axis_name, axis_data in data["kinematics"]["axes"].items():
            axes[axis_name] = AxisConfig(**axis_data)

        extruder = ExtruderConfig(**data["extruder"])

        th = data["thermal"]
        thermal = ThermalConfig(
            hotend=ThermalElementConfig(**th["hotend"]),
            bed=ThermalElementConfig(**th["bed"]),
            ambient_temp=th["ambient_temp"],
        )

        bv = data["build_volume"]
        build_volume = (bv["x"], bv["y"], bv["z"])

        return PrinterModel(
            name=data["name"],
            description=data["description"],
            board=board,
            display=display,
            kinematics_type=data["kinematics"]["type"],
            axes=axes,
            extruder=extruder,
            heated_bed_enabled=data.get("heated_bed", {}).get("enabled", False),
            thermal=thermal,
            build_volume=build_volume,
            features=data.get("features", {}),
            _source_path=path,
        )


def list_models() -> list[str]:
    """Return available model names (filename stems)."""
    return sorted(p.stem for p in MODELS_DIR.glob("*.json"))


def load_model(name: str) -> PrinterModel:
    """Load a printer model by name.

    The name can be a filename stem (e.g. 'ender3v2_skr_mini_e3_v2')
    or a full path to a JSON file.
    """
    path = Path(name)
    if path.is_file():
        return PrinterModel.from_json(path)

    model_path = MODELS_DIR / f"{name}.json"
    if not model_path.exists():
        available = list_models()
        raise FileNotFoundError(
            f"Printer model '{name}' not found. "
            f"Available: {', '.join(available)}"
        )
    return PrinterModel.from_json(model_path)
