# Part C — MarlinSIM Firmware Simulator

A full Marlin firmware simulator that runs **real Marlin 2.x firmware** on your Linux PC
with virtual hardware, a live Web UI display, and interactive controls.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Web Browser (UI)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐│
│  │ LCD View │  │ 3D View  │  │ Controls │  │ G-code Terminal  ││
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────────┬─────────┘│
│       └──────────────┼────────────┼──────────────────┘          │
│                      │ WebSocket                                │
└──────────────────────┼──────────────────────────────────────────┘
                       │
┌──────────────────────┼──────────────────────────────────────────┐
│  Python Host         │                                          │
│  ┌───────────────────▼────────────────────────────────────────┐ │
│  │              WebServer (aiohttp)                           │ │
│  │     HTTP static files  +  WebSocket bidirectional          │ │
│  └───────────────────┬────────────────────────────────────────┘ │
│                      │                                          │
│  ┌───────────────────▼────────────────────────────────────────┐ │
│  │            SimulatorCore (asyncio event loop)              │ │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │ │
│  │  │ ShmClient   │  │ PhysicsEngine│  │ MarlinBuilder    │  │ │
│  │  │ (IPC r/w)   │  │ (thermal,    │  │ (clone, patch,   │  │ │
│  │  │             │  │  motion,     │  │  build Marlin)   │  │ │
│  │  │             │  │  endstops)   │  │                  │  │ │
│  │  └──────┬──────┘  └──────────────┘  └──────────────────┘  │ │
│  └─────────┼─────────────────────────────────────────────────┘ │
│            │  POSIX Shared Memory                               │
│            │  /dev/shm/marlinsim_shm (8KB)                      │
│            │                                                    │
│  ┌─────────▼──────────────────────────────────────────────────┐ │
│  │                     pty (serial I/O)                       │ │
│  └─────────┬──────────────────────────────────────────────────┘ │
└────────────┼────────────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────────────┐
│  Marlin Firmware Process (native Linux binary)                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Marlin 2.x Core (unmodified)                             │ │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐  │ │
│  │  │ Planner │ │ Stepper  │ │ Thermal    │ │ G-code     │  │ │
│  │  │         │ │ ISR      │ │ Manager    │ │ Parser     │  │ │
│  │  └────┬────┘ └────┬─────┘ └─────┬──────┘ └─────┬──────┘  │ │
│  │       └───────────┼─────────────┼───────────────┘         │ │
│  ├────────────────────────────────────────────────────────────┤ │
│  │  HAL Bridge (SIM/)                                        │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │ │
│  │  │ sim_bridge   │  │ sim_display  │  │ MarlinSIM      │   │ │
│  │  │ (SHM IPC)    │  │ (LCD capture)│  │ (Part B module)│   │ │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## IPC Protocol (Shared Memory Layout)

The Marlin process and Python host communicate via a single 8KB POSIX shared memory
segment at `/dev/shm/marlinsim_shm`:

| Offset | Size   | Content                         |
|--------|--------|---------------------------------|
| 0      | 4      | Magic: `MSIM`                   |
| 4      | 4      | Protocol version (1)            |
| 8      | 4      | Flags (running, lcd_dirty, ...) |
| 16     | 2+2    | LCD width, height               |
| 64     | ≤4096  | LCD framebuffer (1-bit packed)  |
| 4160   | 16     | Stepper positions (X,Y,Z,E)    |
| 4176   | 16     | Temperatures (4× float)         |
| 4192   | 6      | Endstop states                  |
| 4200   | 5      | Encoder position + button       |
| 4208   | 2      | Heater PWM (hotend, bed)        |

Serial communication (G-code commands and responses) flows through a PTY
(pseudo-terminal) pair.

## Supported Printer Models

Models are defined as JSON files in `simulator/marlinsim_sim/models/`:

| Model | Board | Display | File |
|-------|-------|---------|------|
| Ender 3 V2 | BTT SKR Mini E3 V2 | ST7920 128×64 | `ender3v2_skr_mini_e3_v2.json` |
| Ender 3 V2 Neo | Creality 4.2.2 | DWIN 272×480 | `ender3v2_neo_creality422.json` |
| Ender 3 S1 Pro | Creality STM32F401 | DWIN 272×480 | `ender3_s1_pro.json` |

### Custom Models

Create your own JSON model file following the schema:

```json
{
    "name": "My Printer",
    "board": { "name": "...", "mcu": "...", "marlin_board": "BOARD_..." },
    "display": { "type": "st7920", "width": 128, "height": 64, ... },
    "kinematics": { "type": "cartesian", "axes": { ... } },
    "extruder": { ... },
    "thermal": { ... },
    "build_volume": { "x": 220, "y": 220, "z": 250 }
}
```

Then: `marlinsim-run -m /path/to/my_printer.json`

## Quick Start

```bash
# Install
cd simulator
pip install -e .

# List available models
marlinsim-run --list-models

# Run with default Ender 3 V2
marlinsim-run -v

# Run with specific model and Marlin version
marlinsim-run -m ender3v2_skr_mini_e3_v2 --marlin-version 2.1.x -vv

# Skip build (use existing compiled Marlin)
marlinsim-run --skip-build -m ender3v2_skr_mini_e3_v2

# Stream a G-code file
marlinsim-run -g my_print.gcode -m ender3v2_skr_mini_e3_v2
```

## Web UI

The simulator starts a web server (default: http://localhost:8080) with:

- **LCD Display**: Pixel-perfect rendering of the simulated display
- **Encoder Controls**: Rotate/click buttons + mouse wheel support
- **3D View**: Wireframe visualization of nozzle position in build volume
- **G-code Terminal**: Interactive command input with history, quick-command buttons
- **Printer State**: Live thermal readings, axis positions, endstop states

## Requirements

- **Linux** (POSIX shared memory + PTY)
- **Python ≥ 3.10**
- **PlatformIO** (for building Marlin)
- **Git** (for cloning Marlin)
- **GCC/G++** (for native compilation)

```bash
# Arch Linux
sudo pacman -S python platformio git gcc

# Ubuntu/Debian
sudo apt install python3 python3-pip git gcc g++
pip install platformio
```

## How It Works

1. **MarlinBuilder** clones the Marlin repository, patches `Configuration.h` and
   `Configuration_adv.h` for the chosen printer model, injects the MarlinSIM
   firmware module (Part B), creates HAL bridge files, and compiles for the
   `linux_native` PlatformIO target.

2. **SimulatorCore** launches the compiled Marlin as a native process, sets up a
   PTY for serial communication and POSIX shared memory for hardware simulation.

3. **PhysicsEngine** runs a 20 Hz update loop: reads stepper positions from SHM,
   simulates thermal behavior (first-order model), checks endstop triggers, and
   writes temperatures and endstop states back for Marlin to read.

4. **WebServer** serves the single-page Web UI and maintains WebSocket connections
   for real-time LCD framebuffer streaming, state updates, encoder events, and
   G-code commands.

## Integration with Parts A & B

Use all three parts together:

```bash
# 1. Post-process G-code with Part A
marlinsim-gcode my_print.gcode -o my_print_animated.gcode --printer ender3v2

# 2. Run simulator with Part C, feeding the animated G-code
marlinsim-run -g my_print_animated.gcode -m ender3v2_skr_mini_e3_v2 -v

# 3. Watch the MarlinSIM animation (Part B) render on the virtual LCD
#    Open http://localhost:8080 in your browser
```
