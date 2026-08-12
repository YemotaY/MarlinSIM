/**
 * MarlinSIM Firmware Module — RLE+Delta Frame Decoder
 *
 * Ultra-low-RAM decoder that processes compressed frame data without
 * ever buffering a full frame. Works scanline-by-scanline:
 *
 * Memory model:
 *   - Two scanline buffers (current + previous) = 2 × ROW_BYTES
 *   - RLE state machine = ~12 bytes
 *   - Total decode RAM: ~44 bytes for 128px wide display
 *
 * The decoder is fed bytes from the parser's buffer and produces
 * complete scanlines that can be pushed directly to the display.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#pragma once

#include "msim_types.h"

#ifdef MARLINSIM_ENABLED

class MsimDecoder {
public:
  /**
   * Initialize the decoder.
   */
  void init();

  /**
   * Begin decoding a new frame.
   *
   * @param is_keyframe  true for keyframe (full), false for delta (XOR)
   * @param width        frame width in pixels
   * @param height       frame height in pixels
   */
  void begin_frame(bool is_keyframe, uint16_t width, uint16_t height);

  /**
   * Feed compressed bytes to the decoder.
   * Call this repeatedly with data from the parser buffer.
   *
   * @param data   Pointer to compressed byte data
   * @param len    Number of bytes available
   * @return       Number of bytes actually consumed
   */
  uint8_t feed(const uint8_t* data, uint8_t len);

  /**
   * Check if a complete scanline has been decoded.
   *
   * @return true if get_scanline() will return valid data
   */
  bool scanline_ready() const { return _scanline_ready; }

  /**
   * Get the current decoded scanline.
   * Valid only when scanline_ready() returns true.
   * After reading, call advance_scanline().
   *
   * @return Pointer to ROW_BYTES of pixel data
   */
  const uint8_t* get_scanline() const { return _scan_cur; }

  /**
   * Get the current scanline Y index (0-based).
   */
  uint16_t get_scanline_y() const { return _scan_y; }

  /**
   * Advance to decoding the next scanline.
   * Copies current → previous for delta decoding.
   */
  void advance_scanline();

  /**
   * Check if the entire frame has been decoded.
   */
  bool frame_complete() const { return _decode_state == MSIM_DEC_COMPLETE; }

  /**
   * Reset decoder state.
   */
  void reset();

private:
  // Scanline double-buffer — THE critical RAM allocation
  // For 128px wide: 16 bytes each = 32 bytes total
  uint8_t _scan_cur[MSIM_SCANLINE_BYTES];   // Current scanline being decoded
  uint8_t _scan_prev[MSIM_SCANLINE_BYTES];  // Previous scanline (for delta)

  // Decoder state
  MsimDecodeState _decode_state;
  bool     _is_keyframe;
  bool     _scanline_ready;

  // Frame geometry
  uint16_t _frame_width;
  uint16_t _frame_height;
  uint8_t  _row_bytes;

  // Scanline tracking
  uint16_t _scan_y;           // Current scanline index
  uint8_t  _scan_col;         // Current byte position within scanline

  // RLE state machine
  uint8_t  _rle_remaining;    // Bytes remaining in current RLE run
  uint8_t  _rle_value;        // Value for repeat runs
  bool     _rle_is_repeat;    // true=repeat, false=literal

  // Internal helpers
  void _output_byte(uint8_t b);
  void _check_scanline_complete();
};

#endif // MARLINSIM_ENABLED
