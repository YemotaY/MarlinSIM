"""Tests for the shared memory client."""

import struct
import pytest

from marlinsim_sim.shm_client import (
    ShmClient,
    SHM_OFF_MAGIC,
    SHM_OFF_VERSION,
    SHM_OFF_FLAGS,
    SHM_OFF_LCD_W,
    SHM_OFF_LCD_H,
    SHM_OFF_STEPPER,
    SHM_OFF_TEMP,
    SHM_OFF_ENDSTOP,
    SHM_OFF_ENCODER,
    SIM_FLAG_RUNNING,
    SIM_FLAG_LCD_DIRTY,
)


@pytest.fixture
def shm():
    """Create and open a SHM client, clean up after test."""
    client = ShmClient(create=True)
    client.open(lcd_w=128, lcd_h=64)
    yield client
    client.close()


class TestShmInit:
    def test_open_creates_shm(self, shm):
        assert shm.is_open()
        assert shm.is_running()

    def test_magic(self, shm):
        # Read the raw shm to check magic — use internal mmap
        assert shm._mm[0:4] == b"MSIM"

    def test_version(self, shm):
        ver = struct.unpack_from("<I", shm._mm, SHM_OFF_VERSION)[0]
        assert ver == 1

    def test_lcd_dimensions(self, shm):
        w = struct.unpack_from("<H", shm._mm, SHM_OFF_LCD_W)[0]
        h = struct.unpack_from("<H", shm._mm, SHM_OFF_LCD_H)[0]
        assert w == 128
        assert h == 64


class TestStepper:
    def test_write_read(self, shm):
        shm.write_stepper_pos(1000, 2000, 3000, 4000)
        x, y, z, e = shm.read_stepper_pos()
        assert x == 1000
        assert y == 2000
        assert z == 3000
        assert e == 4000

    def test_negative_positions(self, shm):
        shm.write_stepper_pos(-100, -200, 0, -500)
        x, y, z, e = shm.read_stepper_pos()
        assert x == -100
        assert y == -200
        assert z == 0
        assert e == -500


class TestTemperature:
    def test_write_read(self, shm):
        shm.write_temperatures(200.5, 0.0, 60.3, 22.0)
        # Read back from raw mmap
        h0 = struct.unpack_from("<f", shm._mm, SHM_OFF_TEMP)[0]
        bed = struct.unpack_from("<f", shm._mm, SHM_OFF_TEMP + 8)[0]
        assert abs(h0 - 200.5) < 0.01
        assert abs(bed - 60.3) < 0.01

    def test_heater_pwm(self, shm):
        # Simulate Marlin writing PWM
        shm._mm[SHM_OFF_TEMP + 16] = 128  # Not actual offset — use heater_pwm
        # Actually test via the proper accessor
        from marlinsim_sim.shm_client import SHM_OFF_HEATER_PWM
        shm._mm[SHM_OFF_HEATER_PWM] = 200
        shm._mm[SHM_OFF_HEATER_PWM + 1] = 100
        h_pwm, b_pwm = shm.read_heater_pwm()
        assert h_pwm == 200
        assert b_pwm == 100


class TestEndstops:
    def test_write_read(self, shm):
        shm.write_endstops(True, False, True, False, False, True)
        raw = [shm._mm[SHM_OFF_ENDSTOP + i] for i in range(6)]
        assert raw == [1, 0, 1, 0, 0, 1]

    def test_all_clear(self, shm):
        shm.write_endstops(False, False, False, False, False, False)
        raw = [shm._mm[SHM_OFF_ENDSTOP + i] for i in range(6)]
        assert raw == [0, 0, 0, 0, 0, 0]


class TestEncoder:
    def test_position_and_button(self, shm):
        shm.write_encoder(42, False)
        pos = struct.unpack_from("<i", shm._mm, SHM_OFF_ENCODER)[0]
        assert pos == 42
        assert not shm._test_flag(8)  # SIM_FLAG_ENCODER_CLICK

    def test_button_pressed(self, shm):
        shm.write_encoder(10, True)
        assert shm._test_flag(8)  # SIM_FLAG_ENCODER_CLICK


class TestFlags:
    def test_running_flag(self, shm):
        assert shm.is_running()
        shm._clear_flag(SIM_FLAG_RUNNING)
        assert not shm.is_running()

    def test_lcd_dirty(self, shm):
        assert not shm.is_lcd_dirty()
        shm._set_flag(SIM_FLAG_LCD_DIRTY)
        assert shm.is_lcd_dirty()
        shm.clear_lcd_dirty()
        assert not shm.is_lcd_dirty()

    def test_close_clears_running(self, shm):
        assert shm.is_running()
        shm.close()
        # After close, the client should not be open
        assert not shm.is_open()


class TestLCD:
    def test_write_read_lcd(self, shm):
        # Simulate Marlin writing LCD data
        test_data = bytes(range(128))
        for i, b in enumerate(test_data):
            shm._mm[64 + i] = b
        shm._set_flag(SIM_FLAG_LCD_DIRTY)

        assert shm.is_lcd_dirty()
        data = shm.read_lcd(128)
        assert data == test_data
        shm.clear_lcd_dirty()
        assert not shm.is_lcd_dirty()
