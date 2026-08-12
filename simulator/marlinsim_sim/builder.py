"""Marlin firmware builder — clones, configures, and compiles Marlin for native simulation."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .models import AxisConfig, PrinterModel

logger = logging.getLogger(__name__)

# Default Marlin repository
MARLIN_REPO = "https://github.com/MarlinFirmware/Marlin.git"

# Native simulation environment name in platformio
NATIVE_ENV = "marlinsim"


class MarlinBuilder:
    """Clones, patches, configures, and compiles Marlin for native (x86/Linux) execution.

    The Marlin linux_native HAL provides a simulated hardware abstraction layer
    that allows the firmware to run as a regular process on the host PC.  We
    extend it with:
      - A PTY-based virtual serial port (stdin/stdout redirection)
      - Shared-memory LCD framebuffer for display streaming
      - Virtual stepper/endstop/temperature hooks via IPC

    Build flow:
      1. clone()    — git clone the requested Marlin version
      2. configure() — patch Configuration.h / Configuration_adv.h for the
                       chosen printer model, inject MarlinSIM module
      3. build()    — compile via PlatformIO for the linux_native target
      4. get_executable() — return path to the compiled binary
    """

    def __init__(
        self,
        printer: PrinterModel,
        marlin_version: str = "2.1.x",
        workspace: Optional[Path] = None,
        marlin_repo: str = MARLIN_REPO,
    ):
        self.printer = printer
        self.marlin_version = marlin_version
        self.marlin_repo = marlin_repo

        if workspace is None:
            workspace = Path.home() / ".marlinsim" / "builds"
        self.workspace = workspace
        self.build_id = f"{printer.name.replace(' ', '_')}_{marlin_version}"
        self.marlin_dir = self.workspace / self.build_id / "Marlin"
        self._executable: Optional[Path] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clone(self, force: bool = False) -> Path:
        """Clone Marlin repository at the specified version/branch."""
        dest = self.marlin_dir
        if dest.exists():
            if force:
                logger.info("Removing existing Marlin clone at %s", dest)
                shutil.rmtree(dest)
            else:
                logger.info("Marlin already cloned at %s", dest)
                return dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Cloning Marlin %s from %s ...", self.marlin_version, self.marlin_repo
        )

        cmd = [
            "git", "clone",
            "--depth", "1",
            "--branch", self.marlin_version,
            self.marlin_repo,
            str(dest),
        ]
        self._run(cmd, cwd=dest.parent)
        logger.info("Clone complete → %s", dest)
        return dest

    def configure(self) -> None:
        """Patch Marlin configuration for native simulation with the printer model."""
        if not self.marlin_dir.exists():
            raise FileNotFoundError(
                f"Marlin directory not found: {self.marlin_dir}. Run clone() first."
            )

        logger.info("Configuring Marlin for %s ...", self.printer.name)

        # 0. Apply compatibility patches for old Marlin + new GCC
        self._apply_compat_patches()

        # 1. Patch platformio.ini to include linux_native env
        self._patch_platformio_ini()

        # 2. Generate Configuration.h overrides
        self._patch_configuration_h()

        # 3. Generate Configuration_adv.h overrides
        self._patch_configuration_adv_h()

        # 4. Inject MarlinSIM firmware module
        self._inject_marlinsim_module()

        # 5. Create the virtual HAL bridge
        self._create_hal_bridge()

        # 6. Hook display, stepper, and temperature into SHM IPC
        self._patch_lcd_com_defines()
        self._patch_marlinui_for_capture()
        self._patch_main_cpp()

        logger.info("Configuration complete.")

    def build(self) -> Path:
        """Build Marlin for native/linux target.  Returns path to executable."""
        if not self.marlin_dir.exists():
            raise FileNotFoundError("Marlin not cloned.  Run clone() first.")

        logger.info("Building Marlin (native) ...")

        pio = self._find_platformio()
        cmd = [str(pio), "run", "-e", NATIVE_ENV]
        self._run(cmd, cwd=self.marlin_dir)

        # Find the built binary
        exe = self._find_executable()
        if exe is None:
            raise RuntimeError("Build succeeded but executable not found.")

        self._executable = exe
        logger.info("Build complete → %s", exe)
        return exe

    def get_executable(self) -> Path:
        """Return path to the built Marlin binary."""
        if self._executable and self._executable.exists():
            return self._executable

        exe = self._find_executable()
        if exe is None:
            raise FileNotFoundError(
                "No Marlin binary found.  Run build() first."
            )
        self._executable = exe
        return exe

    # ------------------------------------------------------------------
    # Configuration patching
    # ------------------------------------------------------------------

    def _apply_compat_patches(self) -> None:
        """Fix known compatibility issues across Marlin versions and GCC versions.

        Older Marlin releases (≤ 2.0.9.x) define short macros like ``_Os``,
        ``_O0`` … ``_O3`` in ``core/macros.h`` which collide with template
        parameter names in GCC ≥ 14 C++ standard-library headers (e.g.
        ``<ostream>`` uses ``_Os`` internally).  Later Marlin branches
        already renamed them to ``__Os`` etc.  We apply the same rename
        when the old names are still present.

        This method also handles ``bresenham.h`` which has its own local
        ``#define _O3``.
        """
        macros_h = self.marlin_dir / "Marlin" / "src" / "core" / "macros.h"
        if not macros_h.exists():
            return

        content = macros_h.read_text()

        # Check whether the old single-underscore names are present
        if "#define _Os " not in content:
            logger.debug("Compat: _Os macro already renamed or absent — skipping")
            return

        logger.info("Compat: renaming _O0/_Os/_O1/_O2/_O3 → __O0/__Os/… (GCC ≥ 14 fix)")

        # Rename definitions in macros.h
        renames = {
            "#define _O0 ": "#define __O0 ",
            "#define _Os ": "#define __Os ",
            "#define _O1 ": "#define __O1 ",
            "#define _O2 ": "#define __O2 ",
            "#define _O3 ": "#define __O3 ",
        }
        for old, new in renames.items():
            content = content.replace(old, new)
        macros_h.write_text(content)

        # Now rename usages across all .h / .cpp files under Marlin/src/
        src_dir = self.marlin_dir / "Marlin" / "src"
        # Patterns: word-boundary _Ox at end of declaration or as function attr
        # We use simple string replacements on token boundaries.
        usage_renames = [
            (" _O0;",  " __O0;"),
            (" _O0 ",  " __O0 "),
            (" _Os;",  " __Os;"),
            (" _Os ",  " __Os "),
            (" _O1;",  " __O1;"),
            (" _O1 ",  " __O1 "),
            (" _O2;",  " __O2;"),
            (" _O2 ",  " __O2 "),
            (" _O3;",  " __O3;"),
            (" _O3 ",  " __O3 "),
            (" _O3\n", " __O3\n"),
        ]
        # Also handle #define _O3 in bresenham.h (standalone re-definition)
        usage_renames.append(("#define _O3 ", "#define __O3 "))

        for fpath in src_dir.rglob("*"):
            if fpath.suffix not in (".h", ".cpp", ".c"):
                continue
            if fpath == macros_h:
                continue  # already patched
            try:
                text = fpath.read_text()
            except (UnicodeDecodeError, OSError):
                continue

            changed = False
            for old, new in usage_renames:
                if old in text:
                    text = text.replace(old, new)
                    changed = True
            if changed:
                fpath.write_text(text)

    def _patch_platformio_ini(self) -> None:
        """Add marlinsim environment to platformio.ini.

        Extends Marlin's built-in ``linux_native`` env (defined in
        ``ini/native.ini``) and adds MarlinSIM-specific defines.
        If the Marlin version doesn't ship a ``linux_native`` env we
        create a complete one from scratch.
        """
        ini_path = self.marlin_dir / "platformio.ini"
        content = ini_path.read_text()

        marker = "[env:marlinsim]"
        if marker in content:
            logger.debug("marlinsim env already present in platformio.ini")
            return

        # Check if Marlin ships its own linux_native env (2.0.x+ does)
        has_native = "[env:linux_native]" in content
        if not has_native:
            # Also check extra_configs / included ini files
            native_ini = self.marlin_dir / "ini" / "native.ini"
            has_native = native_ini.exists() and "[env:linux_native]" in native_ini.read_text()

        if has_native:
            # Detect whether the existing env uses old PlatformIO key names
            # (src_filter / src_build_flags) or new ones (build_src_filter / build_src_flags).
            # Read the linux_native env section from wherever it lives.
            native_text = content
            native_ini = self.marlin_dir / "ini" / "native.ini"
            if native_ini.exists():
                native_text += "\n" + native_ini.read_text()

            uses_old_keys = "src_filter" in native_text and "build_src_filter" not in native_text

            if uses_old_keys:
                # Old PlatformIO (< 6) key names — Marlin ≤ 2.0.9.x
                # PlatformIO 6 still reads them but emits deprecation warnings.
                # We must use the same key name so that common-dependencies.py
                # (which reads/writes ``src_filter``) can properly append
                # feature-dependent source files (G2_G3, M302, etc.) at build
                # time.
                src_filter_key = "src_filter"
                src_filter_ref = "${env:linux_native.src_filter}"
            else:
                src_filter_key = "build_src_filter"
                src_filter_ref = "${env:linux_native.build_src_filter}"

            # Extend the existing linux_native env
            env_block = f"""

#
# MarlinSIM — extends Marlin linux_native with simulation hooks
#
[env:marlinsim]
extends     = env:linux_native
build_flags = ${{env:linux_native.build_flags}}
    -DMARLIN_SIM
    -DMARLINSIM_ENABLED
    -DMARLINSIM_SIM_MODE
{src_filter_key} = {src_filter_ref} +<src/HAL/SIM> +<src/feature/marlinsim>
build_type = debug
"""
        else:
            # Fallback: create a complete native env from scratch
            env_block = """

#
# MarlinSIM — Native Linux simulation (standalone)
#
[env:marlinsim]
platform         = native
framework        =
build_flags      = -D__PLAT_LINUX__ -std=gnu++17 -ggdb -g -lrt -lpthread
    -D__MARLIN_FIRMWARE__ -Wno-expansion-to-defined
    -DMARLIN_SIM
    -DMARLINSIM_ENABLED
    -DMARLINSIM_SIM_MODE
build_src_flags  = -Wall -IMarlin/src/HAL/LINUX/include
build_unflags    = -Wall
lib_ldf_mode     = off
lib_deps         =
build_src_filter = ${common.default_src_filter} +<src/HAL/LINUX> +<src/HAL/SIM> +<src/feature/marlinsim>
build_type       = debug
"""

        content += env_block
        ini_path.write_text(content)
        logger.debug("Added marlinsim env to platformio.ini")

    def _patch_configuration_h(self) -> None:
        """Patch Configuration.h with printer-specific settings."""
        cfg_path = self.marlin_dir / "Marlin" / "Configuration.h"
        if not cfg_path.exists():
            logger.warning("Configuration.h not found, skipping patch")
            return

        content = cfg_path.read_text()

        # Detect whether this Marlin version uses BOARD_SIMULATED (2.1+)
        # or BOARD_LINUX_RAMPS (2.0.x).
        boards_h = self.marlin_dir / "Marlin" / "src" / "core" / "boards.h"
        if boards_h.exists() and "BOARD_SIMULATED" in boards_h.read_text():
            board_name = "BOARD_SIMULATED"
        else:
            board_name = "BOARD_LINUX_RAMPS"

        patches = {
            # Board — use the native/simulated board for this Marlin version
            "MOTHERBOARD": f"  #define MOTHERBOARD {board_name}",
            # Steps per mm
            "DEFAULT_AXIS_STEPS_PER_UNIT": self._steps_define(),
            # Max feedrate
            "DEFAULT_MAX_FEEDRATE": self._feedrate_define(),
            # Max acceleration
            "DEFAULT_MAX_ACCELERATION": self._accel_define(),
            # Thermal
            "TEMP_SENSOR_0": "  #define TEMP_SENSOR_0 1",
            # Display
        }

        if self.printer.heated_bed_enabled:
            patches["TEMP_SENSOR_BED"] = "  #define TEMP_SENSOR_BED 1"

        # Add display defines
        for define in self.printer.display.marlin_defines:
            patches[define] = f"  #define {define}"

        for key, replacement in patches.items():
            pattern = rf"^(\s*#define\s+{re.escape(key)}\b.*$)"
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
            elif key.startswith("BOARD_") or key.startswith("DWIN"):
                # Pure defines without values — add at the end of custom section
                pass

        cfg_path.write_text(content)
        logger.debug("Patched Configuration.h")

    def _patch_configuration_adv_h(self) -> None:
        """Patch Configuration_adv.h for MarlinSIM."""
        cfg_path = self.marlin_dir / "Marlin" / "Configuration_adv.h"
        if not cfg_path.exists():
            logger.warning("Configuration_adv.h not found, skipping patch")
            return

        content = cfg_path.read_text()

        # Add MarlinSIM defines at the end
        marker = "// @section marlinsim"
        if marker not in content:
            addition = f"""
// @section marlinsim
// ==================== MarlinSIM Configuration ====================
#ifndef MARLINSIM_ENABLED
  #define MARLINSIM_ENABLED
#endif
#define MARLINSIM_DISPLAY_WIDTH  {self.printer.display.width}
#define MARLINSIM_DISPLAY_HEIGHT {self.printer.display.height}
#define MSIM_DECODE_BUF_SIZE     128
#define MSIM_PARSE_BUF_SIZE      64
#ifndef MARLINSIM_SIM_MODE
  #define MARLINSIM_SIM_MODE
#endif
// ===============================================================
"""
            content += addition

        cfg_path.write_text(content)
        logger.debug("Patched Configuration_adv.h")

    def _inject_marlinsim_module(self) -> None:
        """Copy the MarlinSIM firmware module into the Marlin source tree."""
        fw_src = Path(__file__).parent.parent.parent / "firmware" / "marlinsim"
        if not fw_src.exists():
            logger.warning(
                "MarlinSIM firmware module not found at %s — skipping injection",
                fw_src,
            )
            return

        dest = self.marlin_dir / "Marlin" / "src" / "feature" / "marlinsim"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(fw_src, dest)
        logger.debug("Injected MarlinSIM module → %s", dest)

    def _create_hal_bridge(self) -> None:
        """Create the HAL bridge files for native simulation.

        These files hook into Marlin's linux_native HAL to provide:
          - Shared-memory LCD framebuffer
          - Virtual serial with PTY
          - Stepper position tracking via /dev/shm
          - Temperature sensor emulation
        """
        bridge_dir = self.marlin_dir / "Marlin" / "src" / "HAL" / "SIM"
        bridge_dir.mkdir(parents=True, exist_ok=True)

        # Main HAL bridge header
        self._write_hal_bridge_h(bridge_dir)
        self._write_hal_bridge_cpp(bridge_dir)
        self._write_hal_display_h(bridge_dir)
        self._write_hal_display_cpp(bridge_dir)
        self._write_sim_u8g_com(bridge_dir)

        logger.debug("Created HAL bridge at %s", bridge_dir)

    # ------------------------------------------------------------------
    # HAL Bridge file generators
    # ------------------------------------------------------------------

    def _write_hal_bridge_h(self, dest: Path) -> None:
        (dest / "sim_bridge.h").write_text("""\
#pragma once
/**
 * MarlinSIM — Virtual Hardware Bridge
 *
 * Provides shared-memory IPC between the Marlin process and the Python
 * simulator host for:
 *   - LCD framebuffer (display pixel data)
 *   - Stepper positions (X/Y/Z/E step counts)
 *   - Temperature readings (hotend, bed)
 *   - Endstop states
 *   - Encoder input (button press, rotation)
 */

#include <cstdint>
#include <cstring>

// Shared memory segment name
#define SIM_SHM_NAME     "/marlinsim_shm"
#define SIM_SHM_SIZE     8192

// Offsets within shared memory
#define SHM_OFF_MAGIC        0    // 4 bytes: 'MSIM'
#define SHM_OFF_VERSION      4    // 4 bytes: protocol version
#define SHM_OFF_FLAGS        8    // 4 bytes: control flags
#define SHM_OFF_LCD_W       16    // 2 bytes: display width
#define SHM_OFF_LCD_H       18    // 2 bytes: display height
#define SHM_OFF_LCD_DATA    64    // LCD framebuffer (up to 4096 bytes)
#define SHM_OFF_STEPPER   4160    // 4x int32_t = 16 bytes (X,Y,Z,E)
#define SHM_OFF_TEMP      4176    // 4x float = 16 bytes (hotend0, hotend1, bed, ambient)
#define SHM_OFF_ENDSTOP   4192    // 6x uint8_t (X_MIN, X_MAX, Y_MIN, Y_MAX, Z_MIN, Z_MAX)
#define SHM_OFF_ENCODER   4200    // int32_t position + uint8_t button
#define SHM_OFF_HEATER_PWM 4208   // 2x uint8_t (hotend, bed) PWM duty 0-255

// Flags
#define SIM_FLAG_RUNNING    (1 << 0)
#define SIM_FLAG_LCD_DIRTY  (1 << 1)
#define SIM_FLAG_KILL       (1 << 2)
#define SIM_FLAG_ENCODER_CLICK (1 << 3)

namespace sim_bridge {

/**
 * Initialize shared memory segment.
 * Called once at Marlin startup from the HAL init.
 */
bool init(uint16_t lcd_w, uint16_t lcd_h);

/** Tear down shared memory. */
void shutdown();

/** Get pointer to the raw shared memory. */
uint8_t* shm_ptr();

/** Write LCD framebuffer data into shared memory. */
void lcd_update(const uint8_t* framebuffer, uint16_t size);

/** Read current stepper positions from sim host. */
void stepper_get_pos(int32_t& x, int32_t& y, int32_t& z, int32_t& e);

/** Write stepper positions (from Marlin stepper ISR). */
void stepper_set_pos(int32_t x, int32_t y, int32_t z, int32_t e);

/** Read temperature values written by sim host. */
float temp_read(uint8_t channel);

/** Write heater PWM duty (from Marlin PID). */
void heater_set_pwm(uint8_t channel, uint8_t duty);

/** Read endstop states from sim host. */
bool endstop_read(uint8_t index);

/** Read encoder position and button from sim host. */
int32_t encoder_position();
bool encoder_button();

/** Set flag. */
void set_flag(uint32_t flag);
void clear_flag(uint32_t flag);
bool test_flag(uint32_t flag);

} // namespace sim_bridge
""")

    def _write_hal_bridge_cpp(self, dest: Path) -> None:
        (dest / "sim_bridge.cpp").write_text("""\
/**
 * MarlinSIM — Virtual Hardware Bridge Implementation
 *
 * Uses POSIX shared memory (/dev/shm) for zero-copy IPC between
 * the Marlin process and the Python simulator host.
 */

#ifdef MARLIN_SIM

#include "sim_bridge.h"

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <cstdio>
#include <cstring>
#include <atomic>

namespace sim_bridge {

static uint8_t* s_shm = nullptr;
static int s_fd = -1;

bool init(uint16_t lcd_w, uint16_t lcd_h) {
    // Create or open shared memory
    s_fd = shm_open(SIM_SHM_NAME, O_CREAT | O_RDWR, 0666);
    if (s_fd < 0) {
        perror("shm_open");
        return false;
    }

    if (ftruncate(s_fd, SIM_SHM_SIZE) < 0) {
        perror("ftruncate");
        close(s_fd);
        return false;
    }

    s_shm = static_cast<uint8_t*>(
        mmap(nullptr, SIM_SHM_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, s_fd, 0)
    );
    if (s_shm == MAP_FAILED) {
        perror("mmap");
        close(s_fd);
        s_shm = nullptr;
        return false;
    }

    // Clear and write magic
    memset(s_shm, 0, SIM_SHM_SIZE);
    memcpy(s_shm + SHM_OFF_MAGIC, "MSIM", 4);

    // Protocol version
    uint32_t ver = 1;
    memcpy(s_shm + SHM_OFF_VERSION, &ver, 4);

    // Display dimensions
    memcpy(s_shm + SHM_OFF_LCD_W, &lcd_w, 2);
    memcpy(s_shm + SHM_OFF_LCD_H, &lcd_h, 2);

    set_flag(SIM_FLAG_RUNNING);

    fprintf(stderr, "[MarlinSIM] SHM bridge initialized: %dx%d\\n", lcd_w, lcd_h);
    return true;
}

void shutdown() {
    if (s_shm) {
        clear_flag(SIM_FLAG_RUNNING);
        munmap(s_shm, SIM_SHM_SIZE);
        s_shm = nullptr;
    }
    if (s_fd >= 0) {
        close(s_fd);
        shm_unlink(SIM_SHM_NAME);
        s_fd = -1;
    }
}

uint8_t* shm_ptr() { return s_shm; }

void lcd_update(const uint8_t* framebuffer, uint16_t size) {
    if (!s_shm) return;
    uint16_t max_size = SIM_SHM_SIZE - SHM_OFF_LCD_DATA;
    if (size > max_size) size = max_size;
    memcpy(s_shm + SHM_OFF_LCD_DATA, framebuffer, size);
    set_flag(SIM_FLAG_LCD_DIRTY);
}

void stepper_get_pos(int32_t& x, int32_t& y, int32_t& z, int32_t& e) {
    if (!s_shm) { x = y = z = e = 0; return; }
    memcpy(&x, s_shm + SHM_OFF_STEPPER + 0, 4);
    memcpy(&y, s_shm + SHM_OFF_STEPPER + 4, 4);
    memcpy(&z, s_shm + SHM_OFF_STEPPER + 8, 4);
    memcpy(&e, s_shm + SHM_OFF_STEPPER + 12, 4);
}

void stepper_set_pos(int32_t x, int32_t y, int32_t z, int32_t e) {
    if (!s_shm) return;
    memcpy(s_shm + SHM_OFF_STEPPER + 0, &x, 4);
    memcpy(s_shm + SHM_OFF_STEPPER + 4, &y, 4);
    memcpy(s_shm + SHM_OFF_STEPPER + 8, &z, 4);
    memcpy(s_shm + SHM_OFF_STEPPER + 12, &e, 4);
}

float temp_read(uint8_t channel) {
    if (!s_shm || channel > 3) return 22.0f;
    float val;
    memcpy(&val, s_shm + SHM_OFF_TEMP + channel * 4, 4);
    return val;
}

void heater_set_pwm(uint8_t channel, uint8_t duty) {
    if (!s_shm || channel > 1) return;
    s_shm[SHM_OFF_HEATER_PWM + channel] = duty;
}

bool endstop_read(uint8_t index) {
    if (!s_shm || index > 5) return false;
    return s_shm[SHM_OFF_ENDSTOP + index] != 0;
}

int32_t encoder_position() {
    if (!s_shm) return 0;
    int32_t pos;
    memcpy(&pos, s_shm + SHM_OFF_ENCODER, 4);
    return pos;
}

bool encoder_button() {
    if (!s_shm) return false;
    return test_flag(SIM_FLAG_ENCODER_CLICK);
}

void set_flag(uint32_t flag) {
    if (!s_shm) return;
    uint32_t flags;
    memcpy(&flags, s_shm + SHM_OFF_FLAGS, 4);
    flags |= flag;
    memcpy(s_shm + SHM_OFF_FLAGS, &flags, 4);
}

void clear_flag(uint32_t flag) {
    if (!s_shm) return;
    uint32_t flags;
    memcpy(&flags, s_shm + SHM_OFF_FLAGS, 4);
    flags &= ~flag;
    memcpy(s_shm + SHM_OFF_FLAGS, &flags, 4);
}

bool test_flag(uint32_t flag) {
    if (!s_shm) return false;
    uint32_t flags;
    memcpy(&flags, s_shm + SHM_OFF_FLAGS, 4);
    return (flags & flag) != 0;
}

} // namespace sim_bridge

#endif // MARLIN_SIM
""")

    def _write_hal_display_h(self, dest: Path) -> None:
        (dest / "sim_display.h").write_text(f"""\
#pragma once
/**
 * MarlinSIM — Virtual Display Driver
 *
 * Captures the U8G framebuffer after each page render and pushes it
 * into shared memory so the Python host can stream it to the Web UI.
 *
 * Display: {self.printer.display.type} {self.printer.display.width}x{self.printer.display.height}
 */

#include <cstdint>

namespace sim_display {{

/** Initialize virtual display. */
void init(uint16_t width, uint16_t height);

/** Called after each U8G page render — captures the page buffer. */
void capture_page(const uint8_t* buf, uint16_t page, uint16_t page_height);

/** Get the complete composited framebuffer. */
const uint8_t* get_framebuffer();

/** Get framebuffer size in bytes. */
uint16_t get_framebuffer_size();

/** Push current framebuffer to shared memory. */
void flush_to_shm();

}} // namespace sim_display
""")

    def _write_hal_display_cpp(self, dest: Path) -> None:
        w = self.printer.display.width
        h = self.printer.display.height
        fb_bytes = (w * h) // 8 if self.printer.display.color_depth == 1 else w * h * 2
        page_bytes = (w // 8) if self.printer.display.color_depth == 1 else w * 2

        (dest / "sim_display.cpp").write_text(f"""\
/**
 * MarlinSIM — Virtual Display Implementation
 */

#ifdef MARLIN_SIM

#include "sim_display.h"
#include "sim_bridge.h"
#include <cstring>
#include <cstdio>

namespace sim_display {{

static uint8_t s_framebuffer[{fb_bytes}];
static uint16_t s_width = {w};
static uint16_t s_height = {h};
static uint16_t s_fb_size = {fb_bytes};

void init(uint16_t width, uint16_t height) {{
    s_width = width;
    s_height = height;
    s_fb_size = (width * height) / 8;  // 1-bit
    memset(s_framebuffer, 0, sizeof(s_framebuffer));
    fprintf(stderr, "[MarlinSIM] Virtual display: %dx%d (%d bytes)\\n",
            width, height, s_fb_size);
}}

void capture_page(const uint8_t* buf, uint16_t page, uint16_t page_height) {{
    // U8G renders in pages of 8 rows.  Copy each page into the right
    // position in our full framebuffer.
    uint16_t row_bytes = s_width / 8;
    uint16_t start_row = page * page_height;
    uint16_t byte_offset = start_row * row_bytes;
    uint16_t copy_size = page_height * row_bytes;

    if (byte_offset + copy_size > s_fb_size) {{
        copy_size = s_fb_size - byte_offset;
    }}

    memcpy(s_framebuffer + byte_offset, buf, copy_size);
}}

const uint8_t* get_framebuffer() {{
    return s_framebuffer;
}}

uint16_t get_framebuffer_size() {{
    return s_fb_size;
}}

void flush_to_shm() {{
    sim_bridge::lcd_update(s_framebuffer, s_fb_size);
}}

}} // namespace sim_display

#endif // MARLIN_SIM
""")

    def _write_sim_u8g_com(self, dest: Path) -> None:
        """Create a U8G COM callback that captures display output for SHM.

        The COM function is the lowest layer the U8G device functions
        call.  Our implementation ignores hardware commands and captures
        all pixel data written via WRITE_SEQ in data mode, building
        up a full framebuffer in shared memory.

        Because different display controllers use different GDRAM
        addressing (e.g. ST7920 splits top/bottom halves), we cannot
        determine actual row positions from the COM layer alone.
        Instead we directly access the U8G page buffer (``pb->buf``)
        which contains the correct pixel data for the current page
        rows, and copy it into our framebuffer using ``pb->p.page_y0``
        as the starting row.
        """
        w = self.printer.display.width
        h = self.printer.display.height
        fb_bytes = (w * h) // 8

        (dest / "sim_u8g_com.cpp").write_text(f"""\
/**
 * MarlinSIM — U8G Communication Driver + Page Capture
 *
 * This COM function always returns success so U8G thinks the display
 * is working.  The actual pixel capture happens via the device-level
 * hook sim_u8g_capture_page() which is called from our patched device
 * functions or from the COM layer's CHIP_SELECT deassert.
 */

#ifdef MARLIN_SIM

#include <cstdio>
#include <cstring>
#include "sim_bridge.h"

static constexpr uint16_t SIM_W = {w};
static constexpr uint16_t SIM_H = {h};
static constexpr uint16_t SIM_FB_SIZE = {fb_bytes};
static constexpr uint16_t SIM_ROW_BYTES = SIM_W / 8;

static uint8_t s_framebuffer[SIM_FB_SIZE];
static bool s_initialized = false;
static uint32_t s_frame_count = 0;

// Forward-declare u8g_t (avoid pulling all u8g headers)
struct _u8g_t;
typedef struct _u8g_t u8g_t;

extern "C" {{

/**
 * Capture a rendered page buffer into the SIM framebuffer.
 *
 * Called from the patched u8g_dev_pb*_base_fn after each PAGE_NEXT,
 * or directly from our wrapper.  page_y0 and page_height come from
 * the u8g_pb_t structure.
 */
void sim_u8g_capture_page(const uint8_t* buf, uint16_t page_y0, uint16_t page_height) {{
    if (!buf) return;
    uint16_t start = page_y0 * SIM_ROW_BYTES;
    uint16_t size  = page_height * SIM_ROW_BYTES;
    if (start + size > SIM_FB_SIZE) size = SIM_FB_SIZE - start;
    memcpy(s_framebuffer + start, buf, size);

    // If we've reached the last page, flush to SHM
    if (page_y0 + page_height >= SIM_H) {{
        sim_bridge::lcd_update(s_framebuffer, SIM_FB_SIZE);
        s_frame_count++;
    }}
}}

/**
 * U8G COM callback — accepts all messages and does nothing.
 * Display rendering is captured via sim_u8g_capture_page().
 */
uint8_t u8g_com_sim_fn(u8g_t *, uint8_t msg, uint8_t arg_val, void *) {{
    (void)arg_val;
    // Accept everything — the virtual display has no real hardware
    // MSG_INIT, MSG_STOP, MSG_ADDRESS, MSG_CHIP_SELECT, MSG_RESET,
    // MSG_WRITE_BYTE, MSG_WRITE_SEQ, MSG_WRITE_SEQ_P
    return 1;
}}

}} // extern "C"

#endif // MARLIN_SIM
""")

    # ------------------------------------------------------------------
    # Marlin source patching — hook SIM bridge into main loop & display
    # ------------------------------------------------------------------

    def _patch_lcd_com_defines(self) -> None:
        """Redirect U8G COM functions to our SIM COM callback.

        Patches ``lcd/dogm/HAL_LCD_com_defines.h`` so that when
        ``MARLIN_SIM`` is defined, all U8G COM function macros point
        to our ``u8g_com_sim_fn`` capture function instead of the
        hardware-specific drivers or the null function.
        """
        defines_h = self.marlin_dir / "Marlin" / "src" / "lcd" / "dogm" / "HAL_LCD_com_defines.h"
        if not defines_h.exists():
            logger.warning("HAL_LCD_com_defines.h not found — skipping display hook")
            return

        content = defines_h.read_text()
        marker = "// MarlinSIM U8G COM override"
        if marker in content:
            return  # Already patched

        # Strategy: insert a MARLIN_SIM block at the top of the file that
        # defines all COM macros, then wraps the rest in #else … #endif.
        override_block = (
            "\n"
            f"// {marker}\n"
            "#ifdef MARLIN_SIM\n"
            "  extern \"C\" uint8_t u8g_com_sim_fn(u8g_t *u8g, uint8_t msg, uint8_t arg_val, void *arg_ptr);\n"
            "  #define U8G_COM_HAL_SW_SPI_FN     u8g_com_sim_fn\n"
            "  #define U8G_COM_HAL_HW_SPI_FN     u8g_com_sim_fn\n"
            "  #define U8G_COM_ST7920_HAL_SW_SPI u8g_com_sim_fn\n"
            "  #define U8G_COM_ST7920_HAL_HW_SPI u8g_com_sim_fn\n"
            "  #define U8G_COM_SSD_I2C_HAL       u8g_com_sim_fn\n"
            "  #define U8G_COM_HAL_TFT_FN        u8g_com_sim_fn\n"
            "#else\n"
        )
        # Find the first #ifndef or #if that starts the platform selection
        import_re = re.compile(r'^(#(?:ifndef|if\s)\s+)', re.MULTILINE)
        m = import_re.search(content)
        if m:
            insert_pos = m.start()
            content = content[:insert_pos] + override_block + content[insert_pos:]
            # Close with #endif at the end of file
            content = content.rstrip() + "\n#endif // !MARLIN_SIM\n"

        defines_h.write_text(content)
        logger.debug("Patched HAL_LCD_com_defines.h with SIM COM override")

    def _patch_marlinui_for_capture(self) -> None:
        """Patch marlinui.cpp to capture U8G page buffers after each page render.

        After each ``u8g.nextPage()`` call (where pages are rendered), we
        call ``sim_u8g_capture_page()`` to copy the page buffer into our
        full framebuffer.  This is the most reliable capture point because:
          - The ``pb->buf`` contains correct row-major pixel data
          - ``pb->p.page_y0`` gives us the exact Y position
          - Works regardless of display controller type
        """
        ui_cpp = self.marlin_dir / "Marlin" / "src" / "lcd" / "marlinui.cpp"
        if not ui_cpp.exists():
            logger.warning("marlinui.cpp not found — skipping display capture hook")
            return

        content = ui_cpp.read_text()
        marker = "// MarlinSIM page capture"
        if marker in content:
            return

        # Strategy: Find the U8G page rendering loop.
        # Pattern in all Marlin versions (2.0.x through 2.1.x):
        #   u8g.firstPage();           // start first page
        #   ...
        #   run_current_screen();      // draw to current page
        #   ...
        #   if (drawing_screen && (drawing_screen = u8g.nextPage()))
        #
        # We need to insert our capture BEFORE the nextPage() call.
        # We look for "run_current_screen();" and add capture after it.

        # Add include at top (after existing includes)
        capture_include = (
            "\n" + marker + "\n"
            "#ifdef MARLIN_SIM\n"
            "  extern \"C\" void sim_u8g_capture_page(const uint8_t* buf, "
            "uint16_t page_y0, uint16_t page_height);\n"
            "#endif\n"
        )
        # Find a good insertion point for the include
        include_pos = content.find("#include")
        if include_pos >= 0:
            eol = content.index("\n", include_pos) + 1
            content = content[:eol] + capture_include + content[eol:]

        # Now find the run_current_screen() call inside the U8G page loop
        # and add our capture hook after it.
        # We search for "run_current_screen();" inside the HAS_MARLINUI_U8GLIB block
        rcs_pattern = "run_current_screen();"
        rcs_pos = content.find(rcs_pattern)
        if rcs_pos >= 0:
            # Find the end of the line
            eol = content.index("\n", rcs_pos) + 1
            capture_hook = (
                "\n"
                "            #ifdef MARLIN_SIM\n"
                "            // Capture the current page buffer for SHM display streaming\n"
                "            {\n"
                "              u8g_pb_t *_simpb = (u8g_pb_t*)(u8g.getU8g()->dev->dev_mem);\n"
                "              if (_simpb && _simpb->buf)\n"
                "                sim_u8g_capture_page((const uint8_t*)_simpb->buf,\n"
                "                                     _simpb->p.page_y0, _simpb->p.page_height);\n"
                "            }\n"
                "            #endif\n"
            )
            content = content[:eol] + capture_hook + content[eol:]

        ui_cpp.write_text(content)
        logger.debug("Patched marlinui.cpp with SIM page capture hook")

    def _patch_main_cpp(self) -> None:
        """Patch the LINUX HAL main.cpp to integrate SIM bridge.

        Hooks:
          - ``sim_bridge::init()`` called at startup
          - Stepper positions written to SHM in ``simulation_loop()``
          - ``sim_bridge::shutdown()`` at exit
        """
        main_cpp = self.marlin_dir / "Marlin" / "src" / "HAL" / "LINUX" / "main.cpp"
        if not main_cpp.exists():
            logger.warning("LINUX HAL main.cpp not found — skipping SIM bridge hook")
            return

        content = main_cpp.read_text()
        marker = "// MarlinSIM bridge hook"
        if marker in content:
            return  # Already patched

        # 1. Add include for sim_bridge at the top (after existing includes)
        include_block = (
            "\n" + marker + "\n"
            "#ifdef MARLIN_SIM\n"
            "  #include \"../SIM/sim_bridge.h\"\n"
            "  #include \"../SIM/sim_display.h\"\n"
            "#endif\n"
        )
        # Insert after the last #include in the file header area
        last_include = content.rfind("#include")
        if last_include >= 0:
            eol = content.index("\n", last_include) + 1
            content = content[:eol] + include_block + content[eol:]

        # 2. Add SIM bridge init in main() before setup()
        init_hook = (
            "\n"
            "#ifdef MARLIN_SIM\n"
            "  sim_bridge::init(MARLINSIM_DISPLAY_WIDTH, MARLINSIM_DISPLAY_HEIGHT);\n"
            "  fprintf(stderr, \"[MarlinSIM] Bridge initialized\\n\");\n"
            "#endif\n\n  "
        )
        setup_idx = content.find("setup();")
        if setup_idx >= 0:
            content = content[:setup_idx] + init_hook + content[setup_idx:]

        # 3. Hook into simulation_loop() to write positions to SHM
        sim_loop_hook = (
            "\n"
            "    #ifdef MARLIN_SIM\n"
            "    sim_bridge::stepper_set_pos(\n"
            "      x_axis.position, y_axis.position,\n"
            "      z_axis.position, extruder0.position);\n"
            "    #endif\n"
        )
        ext_update = content.find("extruder0.update();")
        if ext_update >= 0:
            eol = content.index("\n", ext_update) + 1
            content = content[:eol] + sim_loop_hook + content[eol:]

        main_cpp.write_text(content)
        logger.debug("Patched main.cpp with SIM bridge hooks")

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _steps_define(self) -> str:
        axes = self.printer.axes
        e_steps = self.printer.extruder.steps_per_mm
        x = axes.get("X", AxisConfig(0, 0, 0, -1, 80, 500, 500, "min")).steps_per_mm
        y = axes.get("Y", AxisConfig(0, 0, 0, -1, 80, 500, 500, "min")).steps_per_mm
        z = axes.get("Z", AxisConfig(0, 0, 0, -1, 400, 5, 100, "min")).steps_per_mm
        return f"  #define DEFAULT_AXIS_STEPS_PER_UNIT {{ {x}, {y}, {z}, {e_steps} }}"

    def _feedrate_define(self) -> str:
        axes = self.printer.axes
        e_fr = int(self.printer.extruder.max_feedrate)
        x = int(axes.get("X", AxisConfig(0, 0, 0, -1, 80, 500, 500, "min")).max_feedrate)
        y = int(axes.get("Y", AxisConfig(0, 0, 0, -1, 80, 500, 500, "min")).max_feedrate)
        z = int(axes.get("Z", AxisConfig(0, 0, 0, -1, 400, 5, 100, "min")).max_feedrate)
        return f"  #define DEFAULT_MAX_FEEDRATE {{ {x}, {y}, {z}, {e_fr} }}"

    def _accel_define(self) -> str:
        axes = self.printer.axes
        e_acc = int(self.printer.extruder.max_accel)
        x = int(axes.get("X", AxisConfig(0, 0, 0, -1, 80, 500, 500, "min")).max_accel)
        y = int(axes.get("Y", AxisConfig(0, 0, 0, -1, 80, 500, 500, "min")).max_accel)
        z = int(axes.get("Z", AxisConfig(0, 0, 0, -1, 400, 5, 100, "min")).max_accel)
        return f"  #define DEFAULT_MAX_ACCELERATION {{ {x}, {y}, {z}, {e_acc} }}"

    def _find_executable(self) -> Optional[Path]:
        """Locate the Marlin executable after build."""
        # PlatformIO native build output
        candidates = [
            self.marlin_dir / ".pio" / "build" / NATIVE_ENV / "program",
            self.marlin_dir / ".pio" / "build" / NATIVE_ENV / "firmware",
            self.marlin_dir / ".pio" / "build" / NATIVE_ENV / "marlin_native",
        ]
        for c in candidates:
            if c.exists():
                return c
            # Check with .elf extension
            elf = c.with_suffix(".elf")
            if elf.exists():
                return elf
        return None

    @staticmethod
    def _find_platformio() -> Path:
        """Locate the ``platformio`` CLI.

        Checks (in order):
          1. Same directory as the running Python interpreter (venv ``bin/``)
          2. ``shutil.which("platformio")`` on PATH
          3. ``~/.platformio/penv/bin/platformio`` (PlatformIO installer default)
        """
        import sys

        # 1. Alongside the current Python executable (venv bin/ — don't
        #    resolve symlinks so we stay inside the venv)
        py_dir = Path(sys.executable).parent
        pio_beside_py = py_dir / "platformio"
        if pio_beside_py.is_file():
            return pio_beside_py

        # 2. On PATH
        pio_on_path = shutil.which("platformio")
        if pio_on_path:
            return Path(pio_on_path)

        # 3. PlatformIO's own installer location
        pio_home = Path.home() / ".platformio" / "penv" / "bin" / "platformio"
        if pio_home.is_file():
            return pio_home

        raise FileNotFoundError(
            "PlatformIO CLI not found.  Install it with:  pip install platformio"
        )

    @staticmethod
    def _run(cmd: list[str], cwd: Optional[Path] = None) -> None:
        """Run a subprocess and raise on failure."""
        logger.debug("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("Command failed:\nSTDOUT: %s\nSTDERR: %s",
                         result.stdout[-2000:] if result.stdout else "",
                         result.stderr[-2000:] if result.stderr else "")
            raise RuntimeError(
                f"Command failed (exit {result.returncode}): {' '.join(cmd)}\n"
                f"{result.stderr[-500:]}"
            )
