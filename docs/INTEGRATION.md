# Marlin Firmware Integration Guide

## Overview

This guide explains how to integrate the MarlinSIM animation module into
your Marlin 2.x firmware build.

## Prerequisites

- Marlin 2.x source code (2.0.9+)
- PlatformIO
- A supported board (SKR Mini E3 V2, etc.)
- A supported display (ST7920 128×64, SSD1306, etc.)

## Step 1: Copy Files

Copy the entire `firmware/marlinsim/` directory into your Marlin source tree:

```
Marlin/
├── src/
│   ├── marlinsim/           ← Copy here
│   │   ├── marlinsim.h
│   │   ├── marlinsim.cpp
│   │   ├── msim_config.h
│   │   ├── msim_types.h
│   │   ├── msim_parser.h
│   │   ├── msim_parser.cpp
│   │   ├── msim_decoder.h
│   │   ├── msim_decoder.cpp
│   │   ├── msim_renderer.h
│   │   └── msim_renderer.cpp
│   ├── MarlinCore.cpp
│   └── ...
```

## Step 2: Enable in Configuration

Add to your `Configuration_adv.h`:

```cpp
/**
 * MarlinSIM — 3D Print Progress Animation
 * Displays an animated 3D preview of print progress on the LCD.
 * Requires G-code post-processed by marlinsim-gcode tool.
 */
#define MARLINSIM_ENABLED

// Display resolution (must match your LCD)
#define MARLINSIM_DISPLAY_WIDTH   128
#define MARLINSIM_DISPLAY_HEIGHT  64

// Display update interval in milliseconds
// Lower = smoother animation, higher = less CPU usage
#define MSIM_DISPLAY_UPDATE_MS    500
```

## Step 3: Hook into MarlinCore.cpp

### 3a: Include header

At the top of `MarlinCore.cpp`:

```cpp
#if defined(MARLINSIM_ENABLED)
  #include "marlinsim/marlinsim.h"
#endif
```

### 3b: Initialize in setup()

In the `setup()` function, after display initialization:

```cpp
void setup() {
  // ... existing Marlin setup code ...

  #if defined(MARLINSIM_ENABLED)
    marlinsim_init();
  #endif
}
```

### 3c: Process G-code comments

In `Marlin/src/gcode/parser.cpp` or wherever G-code comments are processed,
add the MarlinSIM character feed:

```cpp
// When processing a comment character:
#if defined(MARLINSIM_ENABLED)
  marlinsim_process_char(c);
#endif

// When end of comment line is reached:
#if defined(MARLINSIM_ENABLED)
  marlinsim_end_comment();
#endif
```

**Specific location in Marlin**: Look for the `process_stream_char()` function
in `gcode/queue.cpp`. When the parser encounters a `;` character, it enters
comment mode. Each subsequent character until newline should be fed to
`marlinsim_process_char()`.

### 3d: Display update

In `Marlin/src/lcd/marlinui.cpp`, in the `MarlinUI::update()` function:

```cpp
void MarlinUI::update() {
  // ... existing update code ...

  #if defined(MARLINSIM_ENABLED)
    marlinsim_update_display();
  #endif
}
```

### 3e: Draw in status screen (U8G displays)

For U8G-based displays (ST7920, SSD1306), in the status screen drawing
function (e.g., `status_screen/dogm/status_screen_DOGM.cpp`):

```cpp
void MarlinUI::draw_status_screen() {
  // Inside the u8g picture loop:
  u8g.firstPage();
  do {
    // ... existing status drawing ...

    #if defined(MARLINSIM_ENABLED)
      if (marlinsim_is_active()) {
        marlinsim_draw_page();
      }
    #endif
  } while (u8g.nextPage());
}
```

### 3f: Print end handler

In the print completion handler:

```cpp
#if defined(MARLINSIM_ENABLED)
  marlinsim_on_print_end();
#endif
```

## Step 4: Build

Build normally with PlatformIO:

```bash
pio run -e STM32F103RC_btt
```

The MarlinSIM module adds approximately:
- **~2.5 KB Flash** (code)
- **~336 bytes RAM** (buffers + state)

## Step 5: Process G-code

Before printing, run the post-processor on your sliced G-code:

```bash
marlinsim-gcode my_print.gcode -o my_print_anim.gcode --printer ender3v2
```

Then print `my_print_anim.gcode` as usual.

## RAM Usage Verification

To verify RAM usage, check the PlatformIO build output:

```
RAM:   [====      ]  XX.X% (used XXXXX bytes from 20480 bytes)
```

MarlinSIM should add ~336 bytes to the RAM usage. If you're already
close to the limit on STM32F103 (20KB), consider:

1. Reducing `MSIM_DECODE_BUF_SIZE` to 64 (saves 64 bytes)
2. Reducing `MSIM_PARSE_BUF_SIZE` to 32 (saves 32 bytes)
3. Disabling other Marlin features you don't need

## Troubleshooting

### No animation displayed
- Check that your G-code was processed with `marlinsim-gcode`
- Look for `; MSIM:H:` at the top of the file
- Enable `MSIM_DEBUG` and check serial output

### Corrupted display
- Verify `MARLINSIM_DISPLAY_WIDTH/HEIGHT` matches your LCD
- Check that the printer profile matches your hardware
- Try increasing `MSIM_DISPLAY_UPDATE_MS`

### Build errors
- Ensure all `.h` and `.cpp` files are in `src/marlinsim/`
- Check that `MARLINSIM_ENABLED` is defined before includes
- Verify Marlin version is 2.0.9 or later

### RAM overflow
- Reduce buffer sizes in `msim_config.h`
- Check total RAM with `pio run -v` and look for `.bss` section
