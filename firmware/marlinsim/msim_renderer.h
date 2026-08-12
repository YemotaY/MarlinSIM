/**
 * MarlinSIM Firmware Module — Scanline LCD Renderer
 *
 * Renders decoded scanlines directly to the display without buffering
 * a full frame. Uses Marlin's u8g/U8G2 display interface.
 *
 * Strategy:
 *   - We hook into Marlin's display update cycle
 *   - When a frame is being decoded, we render it scanline by scanline
 *   - Between frames, we show the last completed frame (stored as
 *     display state — the display itself holds the pixels)
 *
 * RAM usage: ~32 bytes (display command buffer + state)
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include "msim_types.h"

#ifdef MARLINSIM_ENABLED

class MsimRenderer {
public:
  /**
   * Initialize renderer.
   */
  void init();

  /**
   * Push a decoded scanline to the display.
   * Called by the main module when the decoder produces a scanline.
   *
   * @param y         Scanline Y position (0-based)
   * @param data      Pointer to ROW_BYTES of pixel data
   * @param row_bytes Number of bytes in the scanline
   */
  void draw_scanline(uint16_t y, const uint8_t* data, uint8_t row_bytes);

  /**
   * Begin a new frame render.
   * Optionally clears the animation area.
   *
   * @param clear  If true, clear the animation area before drawing
   */
  void begin_frame(bool clear = false);

  /**
   * End frame render — flush any pending display commands.
   */
  void end_frame();

  /**
   * Draw a progress bar below the animation.
   *
   * @param progress  0-100 percent
   */
  void draw_progress(uint8_t progress);

  /**
   * Clear the entire animation area on the display.
   */
  void clear_area();

  /**
   * Check if the renderer is busy (e.g., in a display update cycle).
   */
  bool is_busy() const { return _busy; }

  /**
   * Set the display area for the animation.
   *
   * @param x  Top-left X offset
   * @param y  Top-left Y offset
   * @param w  Width in pixels
   * @param h  Height in pixels
   */
  void set_area(uint16_t x, uint16_t y, uint16_t w, uint16_t h);

private:
  uint16_t _area_x;
  uint16_t _area_y;
  uint16_t _area_w;
  uint16_t _area_h;
  bool     _busy;

  // Display command buffer for batching pixel writes
  uint8_t _cmd_buf[32];
  uint8_t _cmd_len;

  void _flush_cmd();
};

#endif // MARLINSIM_ENABLED
