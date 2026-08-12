"""Tests for the printer model loader."""

import json
import tempfile
from pathlib import Path

import pytest

from marlinsim_sim.models import (
    AxisConfig,
    BoardConfig,
    DisplayConfig,
    ExtruderConfig,
    PrinterModel,
    ThermalConfig,
    ThermalElementConfig,
    list_models,
    load_model,
)


class TestListModels:
    def test_returns_list(self):
        models = list_models()
        assert isinstance(models, list)

    def test_contains_ender3v2(self):
        models = list_models()
        assert "ender3v2_skr_mini_e3_v2" in models

    def test_all_entries_are_strings(self):
        models = list_models()
        for m in models:
            assert isinstance(m, str)

    def test_sorted(self):
        models = list_models()
        assert models == sorted(models)


class TestLoadModel:
    def test_load_ender3v2(self):
        m = load_model("ender3v2_skr_mini_e3_v2")
        assert m.name == "Ender 3 V2"
        assert isinstance(m.board, BoardConfig)
        assert isinstance(m.display, DisplayConfig)
        assert m.board.mcu == "STM32F103RCT6"
        assert m.display.width == 128
        assert m.display.height == 64
        assert m.kinematics_type == "cartesian"

    def test_load_ender3v2_neo(self):
        m = load_model("ender3v2_neo_creality422")
        assert m.name == "Ender 3 V2 Neo"
        assert m.display.type == "dwin"

    def test_load_ender3_s1_pro(self):
        m = load_model("ender3_s1_pro")
        assert m.name == "Ender 3 S1 Pro"
        assert m.board.ram_kb == 96

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_model("nonexistent_printer_model_xyz")

    def test_axes(self):
        m = load_model("ender3v2_skr_mini_e3_v2")
        assert "X" in m.axes
        assert "Y" in m.axes
        assert "Z" in m.axes
        assert m.axes["X"].steps_per_mm == 80.0
        assert m.axes["Z"].steps_per_mm == 400.0

    def test_extruder(self):
        m = load_model("ender3v2_skr_mini_e3_v2")
        assert m.extruder.count == 1
        assert m.extruder.steps_per_mm == 93.0
        assert m.extruder.nozzle_diameter == 0.4

    def test_thermal(self):
        m = load_model("ender3v2_skr_mini_e3_v2")
        assert m.thermal.ambient_temp == 22.0
        assert m.thermal.hotend.heater_power_watts == 40
        assert m.thermal.bed.heater_power_watts == 200

    def test_build_volume(self):
        m = load_model("ender3v2_skr_mini_e3_v2")
        assert m.build_volume == (220.0, 220.0, 250.0)

    def test_features(self):
        m = load_model("ender3v2_skr_mini_e3_v2")
        assert m.features["marlinsim"] is True
        assert m.features["sd_card"] is True


class TestLoadCustomJSON:
    def test_load_from_path(self):
        data = {
            "name": "Test Printer",
            "description": "A test printer",
            "board": {
                "name": "Test Board",
                "mcu": "TEST_MCU",
                "platformio_env": "test_env",
                "marlin_board": "BOARD_TEST",
                "ram_kb": 64,
                "flash_kb": 512,
                "clock_mhz": 100,
            },
            "display": {
                "type": "ssd1306",
                "driver": "U8GLIB_SSD1306_128X64",
                "width": 128,
                "height": 64,
                "color_depth": 1,
                "interface": "i2c",
                "encoder": False,
                "encoder_steps_per_click": 4,
                "beeper": False,
            },
            "kinematics": {
                "type": "corexy",
                "axes": {
                    "X": {
                        "min_pos": 0,
                        "max_pos": 300,
                        "home_pos": 0,
                        "home_dir": -1,
                        "steps_per_mm": 160,
                        "max_feedrate": 300,
                        "max_accel": 3000,
                        "endstop": "min",
                    },
                    "Y": {
                        "min_pos": 0,
                        "max_pos": 300,
                        "home_pos": 0,
                        "home_dir": -1,
                        "steps_per_mm": 160,
                        "max_feedrate": 300,
                        "max_accel": 3000,
                        "endstop": "min",
                    },
                    "Z": {
                        "min_pos": 0,
                        "max_pos": 350,
                        "home_pos": 0,
                        "home_dir": -1,
                        "steps_per_mm": 800,
                        "max_feedrate": 10,
                        "max_accel": 200,
                        "endstop": "min",
                    },
                },
            },
            "extruder": {
                "count": 2,
                "steps_per_mm": 415,
                "max_feedrate": 50,
                "max_accel": 5000,
                "nozzle_diameter": 0.4,
                "filament_diameter": 1.75,
                "max_temp": 300,
                "min_extrude_temp": 180,
            },
            "heated_bed": {"enabled": True},
            "thermal": {
                "hotend": {
                    "thermistor": 1,
                    "pid_p": 20,
                    "pid_i": 1.5,
                    "pid_d": 70,
                    "heater_power_watts": 60,
                    "thermal_mass_j_per_k": 10,
                    "ambient_loss_w_per_k": 0.2,
                },
                "bed": {
                    "thermistor": 1,
                    "pid_p": 50,
                    "pid_i": 1,
                    "pid_d": 800,
                    "heater_power_watts": 300,
                    "thermal_mass_j_per_k": 500,
                    "ambient_loss_w_per_k": 1.5,
                },
                "ambient_temp": 25.0,
            },
            "build_volume": {"x": 300, "y": 300, "z": 350},
            "features": {"marlinsim": True},
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            m = load_model(tmp_path)
            assert m.name == "Test Printer"
            assert m.kinematics_type == "corexy"
            assert m.axes["X"].steps_per_mm == 160
            assert m.extruder.count == 2
            assert m.thermal.ambient_temp == 25.0
            assert m.build_volume == (300, 300, 350)
        finally:
            Path(tmp_path).unlink()
