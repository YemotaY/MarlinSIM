/**
 * MarlinSIM Firmware Module — Compile-time Configuration
 *
 * This file defines all compile-time parameters for the MarlinSIM
 * animation display module. Tuned for minimum RAM usage on
 * STM32F103 (20KB RAM) boards.
 *
 * Include this in your Marlin Configuration_adv.h or define these
 * macros before including marlinsim.h
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

/*============================================================================
 * MASTER ENABLE
 *============================================================================*/

// Uncomment to enable MarlinSIM animation display
// #define MARLINSIM_ENABLED

#ifdef MARLINSIM_ENABLED

/*============================================================================
 * DISPLAY CONFIGURATION
 *============================================================================*/

// Display resolution (must match what Part A generated)
#ifndef MARLINSIM_DISPLAY_WIDTH
  #define MARLINSIM_DISPLAY_WIDTH   128
#endif

#ifndef MARLINSIM_DISPLAY_HEIGHT
  #define MARLINSIM_DISPLAY_HEIGHT  64
#endif

// Bytes per row in packed 1-bit bitmap
#define MSIM_ROW_BYTES    ((MARLINSIM_DISPLAY_WIDTH + 7) / 8)

// Total frame buffer size in bytes (for reference — we DON'T allocate this!)
#define MSIM_FRAME_BYTES  (MSIM_ROW_BYTES * MARLINSIM_DISPLAY_HEIGHT)

/*============================================================================
 * RAM BUDGET — These control the absolute maximum RAM usage
 *============================================================================
 *
 * Total RAM budget target: < 400 bytes
 *
 * Strategy: We NEVER buffer a full frame. Instead we:
 * 1. Decode the RLE stream scanline-by-scanline
 * 2. Keep only the current and previous scanline for delta decoding
 * 3. Push each scanline directly to the display
 */

// RLE decode buffer — holds incoming compressed data chunk
// This is filled from the G-code comment parser one line at a time
#ifndef MSIM_DECODE_BUF_SIZE
  #define MSIM_DECODE_BUF_SIZE  128
#endif

// Scanline buffer — holds ONE decoded scanline (ROW_BYTES each)
// We need two: current + previous (for delta XOR)
// 128px wide = 16 bytes per scanline × 2 = 32 bytes
#define MSIM_SCANLINE_BYTES  MSIM_ROW_BYTES

// G-code line parse buffer for MSIM comments
#ifndef MSIM_PARSE_BUF_SIZE
  #define MSIM_PARSE_BUF_SIZE   64
#endif

// Maximum hex chars we can receive per G-code comment line
#define MSIM_MAX_HEX_PER_LINE  60

/*============================================================================
 * DISPLAY UPDATE CONTROL
 *============================================================================*/

// How often to refresh the display (milliseconds)
// Lower = smoother but more CPU usage during print
#ifndef MSIM_DISPLAY_UPDATE_MS
  #define MSIM_DISPLAY_UPDATE_MS  500
#endif

// Display region for animation (in pixels, from top-left)
// Allows placing the animation in a specific area of the screen
#ifndef MSIM_DISPLAY_OFFSET_X
  #define MSIM_DISPLAY_OFFSET_X  0
#endif

#ifndef MSIM_DISPLAY_OFFSET_Y
  #define MSIM_DISPLAY_OFFSET_Y  0
#endif

/*============================================================================
 * DEBUG
 *============================================================================*/

// Uncomment to enable serial debug output (costs ~200 bytes flash)
// #define MSIM_DEBUG

#ifdef MSIM_DEBUG
  #define MSIM_LOG(msg)     SERIAL_ECHOLNPGM("MSIM: " msg)
  #define MSIM_LOG_VAL(msg, val) do { SERIAL_ECHOPGM("MSIM: " msg " "); SERIAL_ECHOLN(val); } while(0)
#else
  #define MSIM_LOG(msg)          ((void)0)
  #define MSIM_LOG_VAL(msg, val) ((void)0)
#endif

#endif // MARLINSIM_ENABLED
