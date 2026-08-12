/**
 * MarlinSIM Firmware Module — RLE+Delta Frame Decoder Implementation
 *
 * Scanline-by-scanline decoding with absolute minimum RAM.
 * The RLE decoder is a simple state machine that processes one byte at a time.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "msim_decoder.h"

#ifdef MARLINSIM_ENABLED

#include <string.h>  // memset, memcpy

void MsimDecoder::init() {
  reset();
}

void MsimDecoder::reset() {
  _decode_state = MSIM_DEC_IDLE;
  _is_keyframe = false;
  _scanline_ready = false;
  _frame_width = 0;
  _frame_height = 0;
  _row_bytes = 0;
  _scan_y = 0;
  _scan_col = 0;
  _rle_remaining = 0;
  _rle_value = 0;
  _rle_is_repeat = false;
  memset(_scan_cur, 0, sizeof(_scan_cur));
  memset(_scan_prev, 0, sizeof(_scan_prev));
}

void MsimDecoder::begin_frame(bool is_keyframe, uint16_t width, uint16_t height) {
  _is_keyframe = is_keyframe;
  _frame_width = width;
  _frame_height = height;
  _row_bytes = (width + 7) / 8;

  // Clamp to buffer size
  if (_row_bytes > MSIM_SCANLINE_BYTES)
    _row_bytes = MSIM_SCANLINE_BYTES;

  _scan_y = 0;
  _scan_col = 0;
  _scanline_ready = false;
  _rle_remaining = 0;
  _rle_is_repeat = false;

  // Clear current scanline
  memset(_scan_cur, 0, _row_bytes);

  // Clear previous buffer
  // For keyframes: not used
  // For intra-delta: _scan_prev[0] holds the running XOR value, start at 0
  memset(_scan_prev, 0, _row_bytes);

  _decode_state = MSIM_DEC_HEADER;

  MSIM_LOG_VAL("Begin frame, keyframe=", is_keyframe ? 1 : 0);
}

uint8_t MsimDecoder::feed(const uint8_t* data, uint8_t len) {
  if (_decode_state == MSIM_DEC_IDLE || _decode_state == MSIM_DEC_COMPLETE)
    return 0;

  if (_scanline_ready)
    return 0;  // Consumer must call advance_scanline() first

  // First, drain any pending repeat run that was interrupted by a scanline boundary
  if (_decode_state == MSIM_DEC_RLE_REPEAT && _rle_remaining > 0) {
    while (_rle_remaining > 0 && !_scanline_ready) {
      _output_byte(_rle_value);
      _rle_remaining--;
    }
    if (_rle_remaining == 0) {
      _decode_state = MSIM_DEC_RLE_CTRL;
    }
    if (_scanline_ready) return 0;
  }

  uint8_t consumed = 0;

  while (consumed < len && !_scanline_ready) {
    uint8_t b = data[consumed];

    switch (_decode_state) {
      case MSIM_DEC_HEADER:
        // First byte is the frame header (keyframe flag etc.)
        // We already know if it's a keyframe from begin_frame(),
        // but verify/skip the header byte
        _decode_state = MSIM_DEC_RLE_CTRL;
        consumed++;
        break;

      case MSIM_DEC_RLE_CTRL:
        // RLE control byte
        if (b >= 0x80) {
          // Repeat run: count = (b - 0x80 + 2)
          _rle_remaining = (b - 0x80) + 2;
          _rle_is_repeat = true;
          _decode_state = MSIM_DEC_RLE_REPEAT;
        } else {
          // Literal run: count = (b + 1)
          _rle_remaining = b + 1;
          _rle_is_repeat = false;
          _decode_state = MSIM_DEC_RLE_LITERAL;
        }
        consumed++;
        break;

      case MSIM_DEC_RLE_REPEAT:
        // Next byte is the value to repeat
        _rle_value = b;
        consumed++;

        // Output the repeated bytes
        while (_rle_remaining > 0 && !_scanline_ready) {
          _output_byte(_rle_value);
          _rle_remaining--;
        }

        if (_rle_remaining == 0) {
          _decode_state = MSIM_DEC_RLE_CTRL;
        }
        break;

      case MSIM_DEC_RLE_LITERAL:
        // Each byte is a literal value
        _output_byte(b);
        consumed++;
        _rle_remaining--;

        if (_rle_remaining == 0) {
          _decode_state = MSIM_DEC_RLE_CTRL;
        }
        break;

      default:
        consumed++;
        break;
    }
  }

  return consumed;
}

void MsimDecoder::_output_byte(uint8_t b) {
  if (_scan_col >= _row_bytes) {
    // Overflow — skip (safety)
    return;
  }

  if (_is_keyframe) {
    // Keyframe: byte is the actual pixel data
    _scan_cur[_scan_col] = b;
  } else {
    // Intra-frame delta: byte is XOR'd with previous decoded byte
    // _scan_prev[0] stores the last decoded byte for running XOR
    uint8_t prev_byte = _scan_prev[0];
    _scan_cur[_scan_col] = b ^ prev_byte;
    _scan_prev[0] = _scan_cur[_scan_col]; // update running value
  }

  _scan_col++;
  _check_scanline_complete();
}

void MsimDecoder::_check_scanline_complete() {
  if (_scan_col >= _row_bytes) {
    _scanline_ready = true;
  }
}

void MsimDecoder::advance_scanline() {
  if (!_scanline_ready) return;

  // For intra-delta decoding, _scan_prev[0] already holds the running
  // XOR state (updated in _output_byte). No need to copy scanline.

  // Move to next scanline
  _scan_y++;
  _scan_col = 0;
  _scanline_ready = false;

  // Clear next scanline buffer
  memset(_scan_cur, 0, _row_bytes);

  // Check if frame is complete
  if (_scan_y >= _frame_height) {
    _decode_state = MSIM_DEC_COMPLETE;
    MSIM_LOG("Frame decode complete");
  }
}

#endif // MARLINSIM_ENABLED
