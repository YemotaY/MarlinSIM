# MarlinSIM — 3D Print Progress Animation for Marlin 2.x

**Real-time 3D print progress visualization on resource-constrained boards like SKR Mini E3 V2**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

---

## What is MarlinSIM?

MarlinSIM enables **animated 3D print progress visualization** on cheap 3D printer mainboards
(STM32F103 with just 20KB RAM). It works in three parts:

### Part A — `marlinsim-gcode` (Post-Processor)
A Python CLI tool that runs **after slicing**. It:
1. Parses your G-code file
2. Analyzes layer geometry and builds a simplified 3D model
3. Generates ultra-compressed animation frames (RLE + delta encoding)
4. Injects the frame data as special comments into the G-code

### Part B — `marlinsim-fw` (Marlin Firmware Module)
A minimal C++ module compiled into Marlin 2.x that:
1. Reads the injected frame data during printing (zero pre-buffering)
2. Decodes frames on-the-fly with **< 400 bytes RAM** overhead
3. Renders the current print progress as an isometric pixel animation on the LCD

### Part C — `marlinsim-run` (Firmware Simulator)
A full Marlin firmware simulator that:
1. Takes a **freely choosable Marlin >2 version**, printer model, board, and display
2. Compiles and runs **real Marlin firmware** as a native Linux process
3. Simulates axis movements, heating, endstops via shared-memory IPC
4. Provides a **live Web UI** with LCD display streaming, encoder controls, 3D view, and G-code terminal
5. Lets you test MarlinSIM (Parts A & B) **without any real hardware**

---

## RAM Budget (SKR Mini E3 V2 — STM32F103RCT6)

| Component                | RAM Usage |
|--------------------------|-----------|
| Frame decode buffer      | 128 bytes |
| Scanline render buffer   | 64 bytes  |
| State machine            | 48 bytes  |
| Display command buffer   | 32 bytes  |
| G-code parse buffer      | 64 bytes  |
| Lookup tables (PROGMEM)  | 0 bytes   |
| **Total**                | **~336 bytes** |

---

## Quick Start

### Part A: Post-Process G-code

```bash
# Install
pip install marlinsim-gcode

# Or from source
cd gcode_animator
pip install -e .

# Process a sliced file
marlinsim-gcode input.gcode -o output.gcode --printer ender3v2
```

### Part B: Install Firmware Module

1. Copy `firmware/marlinsim/` into your Marlin `src/` directory
2. Add `#include "marlinsim/marlinsim.h"` in `MarlinCore.cpp`
3. Enable in `Configuration_adv.h`:
   ```cpp
   #define MARLINSIM_ENABLED
   #define MARLINSIM_DISPLAY_WIDTH  128
   #define MARLINSIM_DISPLAY_HEIGHT 64
   ```
4. Build & flash as usual with PlatformIO

### Part C: Run the Simulator

```bash
# Install
cd simulator
pip install -e .

# List available printer models
marlinsim-run --list-models

# Run simulator (auto-clones & builds Marlin, opens Web UI)
marlinsim-run -m ender3v2_skr_mini_e3_v2 --marlin-version 2.1.x -v

# Stream a G-code file to the virtual printer
marlinsim-run -g my_print_animated.gcode -m ender3v2_skr_mini_e3_v2

# Open http://localhost:8080 for the interactive Web UI
```

---

## Project Structure

```
MarlinSIM/
├── gcode_animator/          # Part A: Python post-processor
│   ├── marlinsim/
│   │   ├── __init__.py
│   │   ├── cli.py           # CLI entry point
│   │   ├── analyzer.py      # G-code layer analysis
│   │   ├── projector.py     # 3D → 2D isometric projection
│   │   ├── rasterizer.py    # Vector → pixel rasterization
│   │   ├── compressor.py    # RLE + delta frame compression
│   │   ├── injector.py      # Inject frames into G-code
│   │   └── profiles/        # Printer display profiles
│   │       ├── __init__.py
│   │       ├── base.py
│   │       └── ender3v2.py
│   ├── setup.py
│   └── pyproject.toml
│
├── firmware/                 # Part B: Marlin module
│   └── marlinsim/
│       ├── marlinsim.h       # Main include / API
│       ├── marlinsim.cpp     # Core state machine
│       ├── msim_decoder.h    # Frame decoder (RLE+delta)
│       ├── msim_decoder.cpp
│       ├── msim_renderer.h   # Scanline LCD renderer
│       ├── msim_renderer.cpp
│       ├── msim_parser.h     # G-code comment parser
│       ├── msim_parser.cpp
│       ├── msim_config.h     # Compile-time configuration
│       └── msim_types.h      # Shared type definitions
│
├── simulator/                # Part C: Full Marlin simulator
│   ├── marlinsim_sim/
│   │   ├── __init__.py
│   │   ├── cli.py           # CLI: marlinsim-run
│   │   ├── core.py          # Simulator orchestration
│   │   ├── builder.py       # Marlin clone/patch/build
│   │   ├── physics.py       # Thermal + motion simulation
│   │   ├── shm_client.py    # Shared memory IPC client
│   │   ├── server.py        # Web UI server (aiohttp)
│   │   ├── models/          # JSON printer profiles
│   │   │   ├── __init__.py
│   │   │   ├── ender3v2_skr_mini_e3_v2.json
│   │   │   ├── ender3v2_neo_creality422.json
│   │   │   └── ender3_s1_pro.json
│   │   └── web/             # Web UI frontend
│   │       ├── index.html
│   │       ├── style.css
│   │       └── app.js
│   ├── tests/
│   │   ├── test_models.py
│   │   ├── test_physics.py
│   │   ├── test_shm.py
│   │   └── test_builder.py
│   └── pyproject.toml
│
├── tests/
│   ├── test_analyzer.py
│   ├── test_compressor.py
│   ├── test_injector.py
│   ├── test_firmware_decoder.cpp
│   └── fixtures/
│       └── sample.gcode
│
├── docs/
│   ├── PROTOCOL.md           # Frame data format spec
│   ├── INTEGRATION.md        # Marlin integration guide
│   ├── PROFILES.md           # Adding new printers
│   └── SIMULATOR.md          # Part C architecture & usage
│
├── README.md
├── LICENSE
└── .gitignore
```

---

## Supported Hardware

| Board              | MCU           | RAM   | Status |
|--------------------|---------------|-------|--------|
| SKR Mini E3 V2     | STM32F103RCT6 | 20KB  | ✅ Primary target |
| SKR Mini E3 V3     | STM32G0B1     | 144KB | ✅ Supported |
| Creality 4.2.2     | STM32F103RET6 | 20KB  | ✅ Supported |
| BTT SKR V1.4       | LPC1768       | 64KB  | ✅ Supported |

### Supported Displays
- ST7920 128x64 (Ender 3 V2 stock)
- SSD1306 128x64 OLED
- DWIN DGUS (Ender 3 V2 stock color)
- ST7789 (via U8G2)

---

## How It Works

### Frame Data Format (injected into G-code)

```gcode
; Normal G-code
G1 X100 Y100 E5.0 F1500
; MSIM:F:0001:AA55032B...   ← Frame 1 (hex-encoded RLE+delta)
; MSIM:K:0001:0025            ← Keyframe at layer 25
G1 X150 Y100 E5.5 F1500
```

### Compression Pipeline

```
3D Geometry → Isometric Projection → 1-bit Rasterization
    → RLE Encoding → Delta Frames → Hex String in G-code comments
```

Typical frame size: **20-80 bytes** (for 128x64 display = 1024 bytes uncompressed)

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](docs/CONTRIBUTING.md).

Key areas:
- New printer/display profiles
- Compression improvements
- Alternative projection modes
- Testing on different boards

---

## License

This project is licensed under the "GNU GENERAL PUBLIC LICENSE" — see [LICENSE](LICENSE).

This matches Marlin's license for maximum compatibility.
