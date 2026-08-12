"""Tests for the MarlinBuilder configuration generation."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from marlinsim_sim.builder import MarlinBuilder
from marlinsim_sim.models import load_model


@pytest.fixture
def printer():
    return load_model("ender3v2_skr_mini_e3_v2")


@pytest.fixture
def builder(printer):
    with tempfile.TemporaryDirectory() as tmpdir:
        b = MarlinBuilder(
            printer=printer,
            marlin_version="2.1.x",
            workspace=Path(tmpdir),
        )
        yield b


class TestBuilderInit:
    def test_workspace(self, builder):
        assert builder.workspace.exists()

    def test_build_id(self, builder):
        assert "Ender" in builder.build_id
        assert "2.1.x" in builder.build_id

    def test_printer(self, builder, printer):
        assert builder.printer is printer


class TestStepsDefine:
    def test_format(self, builder):
        result = builder._steps_define()
        assert "DEFAULT_AXIS_STEPS_PER_UNIT" in result
        assert "80.0" in result
        assert "400.0" in result
        assert "93.0" in result

    def test_feedrate(self, builder):
        result = builder._feedrate_define()
        assert "DEFAULT_MAX_FEEDRATE" in result
        assert "500" in result

    def test_accel(self, builder):
        result = builder._accel_define()
        assert "DEFAULT_MAX_ACCELERATION" in result
        assert "500" in result


class TestPlatformioIni:
    def test_add_marlinsim_env_standalone(self, builder):
        """Verify marlinsim env gets added as standalone when no linux_native exists."""
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)

        ini = marlin_dir / "platformio.ini"
        ini.write_text("[platformio]\ndefault_envs = mega2560\n\n[env:mega2560]\nplatform = atmelavr\n")

        builder._patch_platformio_ini()
        content = ini.read_text()
        assert "[env:marlinsim]" in content
        assert "platform" in content
        assert "MARLIN_SIM" in content
        assert "__PLAT_LINUX__" in content

    def test_add_marlinsim_env_extends(self, builder):
        """Verify marlinsim env extends linux_native when it exists."""
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)

        ini = marlin_dir / "platformio.ini"
        ini.write_text("[platformio]\ndefault_envs = mega2560\n\n[env:linux_native]\nplatform = native\n")

        builder._patch_platformio_ini()
        content = ini.read_text()
        assert "[env:marlinsim]" in content
        assert "extends" in content
        assert "env:linux_native" in content
        assert "MARLIN_SIM" in content

    def test_extends_uses_old_src_filter_key(self, builder):
        """When linux_native uses old 'src_filter', marlinsim env should match."""
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)

        ini = marlin_dir / "platformio.ini"
        ini.write_text(
            "[platformio]\ndefault_envs = mega2560\n\n"
            "[env:linux_native]\nplatform = native\n"
            "src_filter = ${common.default_src_filter} +<src/HAL/LINUX>\n"
        )

        builder._patch_platformio_ini()
        content = ini.read_text()
        # Must use 'src_filter' (not 'build_src_filter') so that
        # common-dependencies.py can read/modify it for feature files.
        assert "\nsrc_filter = ${env:linux_native.src_filter}" in content
        assert "build_src_filter" not in content.split("[env:marlinsim]")[1]

    def test_extends_uses_new_build_src_filter_key(self, builder):
        """When linux_native uses new 'build_src_filter', marlinsim should too."""
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)

        ini = marlin_dir / "platformio.ini"
        ini.write_text(
            "[platformio]\ndefault_envs = mega2560\n\n"
            "[env:linux_native]\nplatform = native\n"
            "build_src_filter = ${common.default_src_filter} +<src/HAL/LINUX>\n"
        )

        builder._patch_platformio_ini()
        content = ini.read_text()
        assert "build_src_filter = ${env:linux_native.build_src_filter}" in content

    def test_idempotent(self, builder):
        """Adding the env twice should not duplicate."""
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)
        ini = marlin_dir / "platformio.ini"
        ini.write_text("[platformio]\ndefault_envs = mega2560\n")

        builder._patch_platformio_ini()
        builder._patch_platformio_ini()
        content = ini.read_text()
        assert content.count("[env:marlinsim]") == 1


class TestConfigurationAdv:
    def test_add_marlinsim_defines(self, builder):
        marlin_dir = builder.marlin_dir
        (marlin_dir / "Marlin").mkdir(parents=True, exist_ok=True)
        cfg = marlin_dir / "Marlin" / "Configuration_adv.h"
        cfg.write_text("// Configuration_adv.h\n#define SOME_SETTING\n")

        builder._patch_configuration_adv_h()
        content = cfg.read_text()
        assert "MARLINSIM_ENABLED" in content
        assert "MARLINSIM_DISPLAY_WIDTH  128" in content
        assert "MARLINSIM_DISPLAY_HEIGHT 64" in content
        assert "MARLINSIM_SIM_MODE" in content


class TestHALBridge:
    def test_creates_bridge_files(self, builder):
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)

        builder._create_hal_bridge()

        bridge_dir = marlin_dir / "Marlin" / "src" / "HAL" / "SIM"
        assert bridge_dir.exists()
        assert (bridge_dir / "sim_bridge.h").exists()
        assert (bridge_dir / "sim_bridge.cpp").exists()
        assert (bridge_dir / "sim_display.h").exists()
        assert (bridge_dir / "sim_display.cpp").exists()

    def test_bridge_h_content(self, builder):
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)
        builder._create_hal_bridge()

        content = (marlin_dir / "Marlin" / "src" / "HAL" / "SIM" / "sim_bridge.h").read_text()
        assert "SIM_SHM_NAME" in content
        assert "/marlinsim_shm" in content
        assert "lcd_update" in content
        assert "stepper_set_pos" in content
        assert "temp_read" in content

    def test_display_dimensions(self, builder):
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)
        builder._create_hal_bridge()

        content = (marlin_dir / "Marlin" / "src" / "HAL" / "SIM" / "sim_display.cpp").read_text()
        assert "128" in content  # width
        assert "64" in content   # height

    def test_sim_u8g_com_created(self, builder):
        """Verify _create_hal_bridge produces sim_u8g_com.cpp."""
        marlin_dir = builder.marlin_dir
        marlin_dir.mkdir(parents=True, exist_ok=True)
        builder._create_hal_bridge()

        com_file = marlin_dir / "Marlin" / "src" / "HAL" / "SIM" / "sim_u8g_com.cpp"
        assert com_file.exists()
        content = com_file.read_text()
        assert "u8g_com_sim_fn" in content
        assert "sim_u8g_capture_page" in content


class TestLCDComDefinesPatch:
    def test_patches_defines_file(self, builder):
        """Verify _patch_lcd_com_defines injects MARLIN_SIM COM override."""
        marlin_dir = builder.marlin_dir
        defines_path = marlin_dir / "Marlin" / "src" / "lcd" / "dogm"
        defines_path.mkdir(parents=True, exist_ok=True)
        defines_h = defines_path / "HAL_LCD_com_defines.h"
        defines_h.write_text(
            '#ifndef U8G_HAL_LINKS\n'
            '  #define U8G_COM_HAL_SW_SPI_FN u8g_com_null_fn\n'
            '#endif\n'
        )
        builder._patch_lcd_com_defines()
        content = defines_h.read_text()
        assert "#ifdef MARLIN_SIM" in content
        assert "u8g_com_sim_fn" in content
        assert "#else" in content

    def test_idempotent(self, builder):
        """Patching twice should not duplicate."""
        marlin_dir = builder.marlin_dir
        defines_path = marlin_dir / "Marlin" / "src" / "lcd" / "dogm"
        defines_path.mkdir(parents=True, exist_ok=True)
        defines_h = defines_path / "HAL_LCD_com_defines.h"
        defines_h.write_text(
            '#ifndef U8G_HAL_LINKS\n'
            '  #define U8G_COM_HAL_SW_SPI_FN u8g_com_null_fn\n'
            '#endif\n'
        )
        builder._patch_lcd_com_defines()
        builder._patch_lcd_com_defines()
        content = defines_h.read_text()
        assert content.count("MarlinSIM U8G COM override") == 1


class TestMarlinUIPatch:
    def test_patches_marlinui(self, builder):
        """Verify _patch_marlinui_for_capture hooks page capture."""
        marlin_dir = builder.marlin_dir
        lcd_dir = marlin_dir / "Marlin" / "src" / "lcd"
        lcd_dir.mkdir(parents=True, exist_ok=True)
        ui_cpp = lcd_dir / "marlinui.cpp"
        ui_cpp.write_text(
            '#include "marlinui.h"\n'
            '#include "other.h"\n'
            'void MarlinUI::update() {\n'
            '  if (do_u8g_loop) {\n'
            '    u8g.firstPage();\n'
            '    run_current_screen();\n'
            '    drawing_screen = u8g.nextPage();\n'
            '  }\n'
            '}\n'
        )
        builder._patch_marlinui_for_capture()
        content = ui_cpp.read_text()
        assert "sim_u8g_capture_page" in content
        assert "MARLIN_SIM" in content
        assert "_simpb" in content

    def test_idempotent(self, builder):
        """Patching twice should not duplicate."""
        marlin_dir = builder.marlin_dir
        lcd_dir = marlin_dir / "Marlin" / "src" / "lcd"
        lcd_dir.mkdir(parents=True, exist_ok=True)
        ui_cpp = lcd_dir / "marlinui.cpp"
        ui_cpp.write_text(
            '#include "marlinui.h"\n'
            'void MarlinUI::update() {\n'
            '  run_current_screen();\n'
            '}\n'
        )
        builder._patch_marlinui_for_capture()
        builder._patch_marlinui_for_capture()
        content = ui_cpp.read_text()
        assert content.count("sim_u8g_capture_page") == 2  # declaration + call


class TestMainCppPatch:
    def test_patches_main_cpp(self, builder):
        """Verify _patch_main_cpp adds bridge init and stepper hook."""
        marlin_dir = builder.marlin_dir
        hal_dir = marlin_dir / "Marlin" / "src" / "HAL" / "LINUX"
        hal_dir.mkdir(parents=True, exist_ok=True)
        main_cpp = hal_dir / "main.cpp"
        main_cpp.write_text(
            '#include <stdio.h>\n'
            '#include "../../inc/MarlinConfig.h"\n'
            'void simulation_loop() {\n'
            '  for (;;) {\n'
            '    extruder0.update();\n'
            '    std::this_thread::yield();\n'
            '  }\n'
            '}\n'
            'int main() {\n'
            '  setup();\n'
            '  for (;;) loop();\n'
            '}\n'
        )
        builder._patch_main_cpp()
        content = main_cpp.read_text()
        assert "sim_bridge" in content
        assert "stepper_set_pos" in content
        assert "MARLIN_SIM" in content

    def test_idempotent(self, builder):
        """Patching twice should not duplicate."""
        marlin_dir = builder.marlin_dir
        hal_dir = marlin_dir / "Marlin" / "src" / "HAL" / "LINUX"
        hal_dir.mkdir(parents=True, exist_ok=True)
        main_cpp = hal_dir / "main.cpp"
        main_cpp.write_text(
            '#include "../../inc/MarlinConfig.h"\n'
            'void simulation_loop() {\n'
            '  extruder0.update();\n'
            '}\n'
            'int main() {\n'
            '  setup();\n'
            '}\n'
        )
        builder._patch_main_cpp()
        builder._patch_main_cpp()
        content = main_cpp.read_text()
        assert content.count("sim_bridge::init") == 1
