# Adding New Printer Profiles

## Overview

Printer profiles tell the MarlinSIM post-processor about your specific
printer's display size and build volume. This ensures the generated
animation frames match your hardware.

## Creating a Profile

### Step 1: Create a new profile file

Create a new Python file in `gcode_animator/marlinsim/profiles/`:

```python
# my_printer.py
from .base import PrinterProfile

class MyPrinterProfile(PrinterProfile):
    """Profile for My Printer with XYZ board."""
    
    def __init__(self):
        super().__init__(
            name="myprinter",
            description="My Printer — SSD1306 128x64 OLED",
            display_width=128,
            display_height=64,
            display_type="ssd1306",
            build_volume_x=200.0,
            build_volume_y=200.0,
            build_volume_z=200.0,
            max_frame_bytes=120,
            supports_grayscale=False,
        )
```

### Step 2: Register the profile

In `gcode_animator/marlinsim/profiles/__init__.py`, add:

```python
from .my_printer import MyPrinterProfile

# At the bottom of the file:
register_profile(MyPrinterProfile())
```

### Step 3: Test

```bash
marlinsim-gcode --list-printers
# Should show your new profile

marlinsim-gcode input.gcode -o output.gcode --printer myprinter
```

## Profile Parameters

| Parameter          | Type   | Description                              |
|--------------------|--------|------------------------------------------|
| `name`             | str    | Unique identifier (lowercase, no spaces) |
| `description`      | str    | Human-readable description               |
| `display_width`    | int    | Display width in pixels                  |
| `display_height`   | int    | Display height in pixels                 |
| `display_type`     | str    | Display controller type                  |
| `build_volume_x`   | float  | Build volume X in mm                     |
| `build_volume_y`   | float  | Build volume Y in mm                     |
| `build_volume_z`   | float  | Build volume Z in mm                     |
| `max_frame_bytes`  | int    | Max compressed frame size (bytes)        |
| `supports_grayscale` | bool | Whether display supports grayscale       |

## Display Types

| Type       | Resolution | Notes                          |
|------------|------------|--------------------------------|
| `st7920`   | 128×64     | Most common on budget printers |
| `ssd1306`  | 128×64     | OLED displays                  |
| `ssd1309`  | 128×64     | OLED (larger)                  |
| `dwin`     | 480×272+   | Color DWIN DGUS displays       |
| `st7789`   | 240×320    | Color TFT (via U8G2)          |

## Firmware Configuration

Remember to also update the firmware configuration to match:

```cpp
// In Configuration_adv.h
#define MARLINSIM_DISPLAY_WIDTH   128  // Must match profile
#define MARLINSIM_DISPLAY_HEIGHT  64   // Must match profile
```

## Contributing Profiles

When submitting a new profile:
1. Test on actual hardware
2. Include board and display details in the docstring
3. Add to the profile registry in `__init__.py`
4. Update this document
