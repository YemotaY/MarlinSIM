/**
 * MarlinSIM Firmware Module — Scanline LCD Renderer Implementation
 *
 * Renders directly to the display using Marlin's U8G interface.
 * Designed to be called from within Marlin's LCD update cycle
 * (u8g picture loop).
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "msim_renderer.h"

#ifdef MARLINSIM_ENABLED

// Forward declarations for Marlin display functions
// These are resolved at link time when compiled with Marlin
#if defined(U8GLIB_ST7920) || defined(U8GLIB_SSD1306) || defined(HAS_MARLINUI_U8GLIB)
  extern "C" {
    // We'll use Marlin's u8g object directly
  }
  #define MSIM_HAS_U8G 1
#else
  #define MSIM_HAS_U8G 0
#endif

#include <string.h>

void MsimRenderer::init() {
  _area_x = MSIM_DISPLAY_OFFSET_X;
  _area_y = MSIM_DISPLAY_OFFSET_Y;
  _area_w = MARLINSIM_DISPLAY_WIDTH;
  _area_h = MARLINSIM_DISPLAY_HEIGHT;
  _busy = false;
  _cmd_len = 0;
  memset(_cmd_buf, 0, sizeof(_cmd_buf));
}

void MsimRenderer::set_area(uint16_t x, uint16_t y, uint16_t w, uint16_t h) {
  _area_x = x;
  _area_y = y;
  _area_w = w;
  _area_h = h;
}

void MsimRenderer::begin_frame(bool clear) {
  _busy = true;
  if (clear) {
    clear_area();
  }
}

void MsimRenderer::end_frame() {
  _flush_cmd();
  _busy = false;
}

void MsimRenderer::draw_scanline(uint16_t y, const uint8_t* data, uint8_t row_bytes) {
  if (y >= _area_h) return;

  /**
   * Render strategy for U8G displays:
   *
   * U8G uses a "picture loop" model where the display is drawn in pages.
   * We integrate by checking if the current scanline Y falls within the
   * active U8G page, and if so, directly set the pixels.
   *
   * For non-U8G displays (DWIN etc.), we use a different approach
   * with direct pixel/bitmap commands.
   */

  #if MSIM_HAS_U8G
    // Direct pixel drawing via U8G
    // In Marlin, this would use: u8g.drawXBMP(x, y, w, 1, data)
    // or pixel-by-pixel via u8g.drawPixel()
    //
    // We use the XBM method as it's most efficient for scanlines.
    // NOTE: This function is called within u8g's picture loop,
    // so we let Marlin's framework handle page clipping.

    // Placeholder — actual Marlin integration uses:
    // u8g.drawXBMP(_area_x, _area_y + y, _area_w, 1, data);

    // For now, buffer the command
    // In actual Marlin build, this resolves to u8g calls
    (void)data;
    (void)row_bytes;

  #else
    // Fallback: No display support
    (void)y;
    (void)data;
    (void)row_bytes;
  #endif
}

void MsimRenderer::draw_progress(uint8_t progress) {
  if (progress > 100) progress = 100;

  #if MSIM_HAS_U8G
    // Draw a simple progress bar below the animation area
    // Bar position: below animation, 2px gap
    // uint16_t bar_y = _area_y + _area_h + 2;
    // uint16_t bar_w = (_area_w * progress) / 100;
    // u8g.drawFrame(_area_x, bar_y, _area_w, 4);
    // u8g.drawBox(_area_x + 1, bar_y + 1, bar_w - 2, 2);
    (void)progress;
  #else
    (void)progress;
  #endif
}

void MsimRenderer::clear_area() {
  #if MSIM_HAS_U8G
    // In Marlin's picture loop, clearing is handled by not drawing
    // The page buffer is cleared each iteration
  #endif
}

void MsimRenderer::_flush_cmd() {
  // Flush any buffered display commands
  _cmd_len = 0;
}

#endif // MARLINSIM_ENABLED
