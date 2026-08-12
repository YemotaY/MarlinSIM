"""Tests for the physics simulation engine."""

import pytest

from marlinsim_sim.models import load_model
from marlinsim_sim.physics import PhysicsEngine, ThermalState, ThermalElementConfig


@pytest.fixture
def printer():
    return load_model("ender3v2_skr_mini_e3_v2")


@pytest.fixture
def engine(printer):
    return PhysicsEngine(printer)


class TestAxisState:
    def test_initial_positions(self, engine):
        positions = engine.get_positions_mm()
        assert positions["X"] == 0.0
        assert positions["Y"] == 0.0
        assert positions["Z"] == 0.0
        assert positions["E"] == 0.0

    def test_step_to_position(self, engine):
        # 80 steps/mm → 8000 steps = 100mm
        engine.set_stepper_positions(8000, 4000, 2000, 0)
        engine.update(0.05)
        pos = engine.get_positions_mm()
        assert abs(pos["X"] - 100.0) < 0.01
        assert abs(pos["Y"] - 50.0) < 0.01
        assert abs(pos["Z"] - 5.0) < 0.01

    def test_endstop_triggered_at_min(self, engine):
        engine.set_stepper_positions(0, 0, 0, 0)
        engine.update(0.05)
        endstops = engine.get_endstop_states()
        assert endstops["X"] is True
        assert endstops["Y"] is True
        assert endstops["Z"] is True

    def test_endstop_not_triggered_in_middle(self, engine):
        engine.set_stepper_positions(8000, 8000, 8000, 0)
        engine.update(0.05)
        endstops = engine.get_endstop_states()
        assert endstops["X"] is False
        assert endstops["Y"] is False
        assert endstops["Z"] is False


class TestThermalModel:
    def test_initial_temperature(self, engine):
        ht, bt, at = engine.get_temperatures()
        assert ht == pytest.approx(22.0)
        assert bt == pytest.approx(22.0)
        assert at == pytest.approx(22.0)

    def test_heating(self, engine):
        """With full power, temperature should increase."""
        engine.set_heater_pwm(255, 0)
        # Simulate 10 seconds
        for _ in range(200):
            engine.update(0.05)
        ht, bt, _ = engine.get_temperatures()
        assert ht > 25.0  # should have heated up
        assert bt == pytest.approx(22.0, abs=0.5)  # bed should be near ambient

    def test_cooling(self, engine):
        """Start hot, no power → should cool down."""
        engine.hotend.current_temp = 200.0
        engine.set_heater_pwm(0, 0)
        for _ in range(200):
            engine.update(0.05)
        ht, _, _ = engine.get_temperatures()
        assert ht < 200.0
        assert ht > 22.0  # shouldn't cool all the way in 10s

    def test_bed_heating(self, engine):
        engine.set_heater_pwm(0, 255)
        for _ in range(200):
            engine.update(0.05)
        _, bt, _ = engine.get_temperatures()
        assert bt > 22.0

    def test_thermal_element_step(self):
        cfg = ThermalElementConfig(
            thermistor=1,
            pid_p=20.0,
            pid_i=1.0,
            pid_d=70.0,
            heater_power_watts=40.0,
            thermal_mass_j_per_k=8.0,
            ambient_loss_w_per_k=0.15,
        )
        ts = ThermalState(
            current_temp=22.0,
            target_temp=200.0,
            pwm_duty=255,
            config=cfg,
            ambient_temp=22.0,
        )
        # One second of heating
        for _ in range(100):
            ts.step(0.01)
        assert ts.current_temp > 22.0
        # P = 40W, C = 8 J/K → dT ≈ 40/8 = 5°/s
        assert ts.current_temp == pytest.approx(27.0, abs=1.0)


class TestStateSerialization:
    def test_to_state_dict(self, engine):
        state = engine.to_state_dict()
        assert "axes" in state
        assert "thermal" in state
        assert "encoder" in state
        assert "X" in state["axes"]
        assert "hotend" in state["thermal"]
        assert "bed" in state["thermal"]
        assert "position" in state["encoder"]

    def test_state_dict_types(self, engine):
        engine.set_stepper_positions(100, 200, 300, 400)
        engine.update(0.05)
        state = engine.to_state_dict()
        assert isinstance(state["axes"]["X"]["position_mm"], float)
        assert isinstance(state["axes"]["X"]["position_steps"], int)
        assert isinstance(state["thermal"]["hotend"]["current"], float)
